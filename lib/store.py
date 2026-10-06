"""§5.16 / §5.14 Sheets → Postgres cutover — dual-write mirror + backfill.

The cutover is two steps (task line 38: "dual-write then retire Sheets"):

1. **Dual-write (this module).** Sheets stays the live read source; every
   Sheets write is mirrored, best-effort, into Postgres so the two stores stay
   in sync and the new store accumulates the full history.
2. **Retire Sheets reads** — a later switch once the mirror has been verified.

The mirror is wired at the one place all pipeline writes funnel through
(`tools/sheet_tool.manage_sheet_data` append), so no agent/tool has to change.
Pure mapping + DB upserts: no LLM, no network, never raises (a mirror failure
must not break the Sheets write that triggered it).

Column layouts mirror docs/service_setup.md:
- research_data:  Keyword/Topic, Search Volume, Difficulty, User Intent,
                  Content Summary, Source URLs, Source Titles, Generated
- content_briefs: Keyword/Topic, Brief Content, FAQs, External Source Links,
                  Content Summary, Generated
- generated_posts: Title, Generated Content, FAQs, Quality Score, Summary,
                  Approve/Disapprove, Published (+ appended cols)
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from lib.db import Article, KeywordLedger, Site, get_session, init_db
from lib.ledger import upsert_keyword

logger = logging.getLogger(__name__)

DUALWRITE_ENABLED = os.environ.get("DUALWRITE_ENABLED", "1").strip().lower() not in (
    "0", "false", "no", "off",
)
DEFAULT_SITE_SLUG = os.environ.get("DEFAULT_SITE_SLUG") or "owaisabdullah-dev"

# Which worksheet maps to which Postgres entity. Unknown worksheets are ignored.
SHEET_TARGETS: Dict[str, str] = {
    "research_data": "keyword",
    "content_briefs": "brief",
    "generated_posts": "article",
    "approved_unpublished": "article",
}

_RESEARCH_HEADERS = [
    "Keyword/Topic", "Search Volume", "Difficulty", "User Intent",
    "Content Summary", "Source URLs", "Source Titles", "Generated",
]
_BRIEF_HEADERS = [
    "Keyword/Topic", "Brief Content", "FAQs", "External Source Links",
    "Content Summary", "Generated",
]
_POST_HEADERS = [
    "Title", "Generated Content", "FAQs", "Quality Score", "Summary",
    "Approve/Disapprove", "Published",
]


# ---------------------------------------------------------------------------
# Coercion helpers
# ---------------------------------------------------------------------------
def _cell(row: List[Any], headers: Optional[List[str]], name: str,
          fallback_index: Optional[int] = None, default: str = "") -> str:
    if headers and name in headers:
        i = headers.index(name)
        return str(row[i]) if i < len(row) and row[i] is not None else default
    if fallback_index is not None and fallback_index < len(row) and row[fallback_index] is not None:
        return str(row[fallback_index])
    return default


def _to_int(v: Any, default: int = 0) -> int:
    try:
        return int(float(str(v).replace(",", "").strip() or 0))
    except (TypeError, ValueError):
        return default


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(str(v).replace(",", "").strip() or 0)
    except (TypeError, ValueError):
        return default


def _is_yes(v: Any) -> bool:
    return str(v).strip().lower() in ("yes", "true", "1", "y", "approved")


# ---------------------------------------------------------------------------
# Row mappers
# ---------------------------------------------------------------------------
def map_research_row(row: List[Any], headers: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "keyword": _cell(row, headers, "Keyword/Topic", 0),
        "volume": _to_int(_cell(row, headers, "Search Volume", 1)),
        "difficulty": _to_float(_cell(row, headers, "Difficulty", 2)),
        "intent": _cell(row, headers, "User Intent", 3, default="informational") or "informational",
        "summary": _cell(row, headers, "Content Summary", 4),
        "generated": _is_yes(_cell(row, headers, "Generated", 7)),
    }


def map_brief_row(row: List[Any], headers: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "keyword": _cell(row, headers, "Keyword/Topic", 0),
        "brief_content": _cell(row, headers, "Brief Content", 1),
        "faqs": _cell(row, headers, "FAQs", 2),
        "sources": _cell(row, headers, "External Source Links", 3),
        "summary": _cell(row, headers, "Content Summary", 4),
        "generated": _is_yes(_cell(row, headers, "Generated", 5)),
    }


def map_generated_post_row(row: List[Any], headers: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "title": _cell(row, headers, "Title", 0),
        "content": _cell(row, headers, "Generated Content", 1),
        "faqs": _cell(row, headers, "FAQs", 2),
        "quality_score": _to_float(_cell(row, headers, "Quality Score", 3)),
        "summary": _cell(row, headers, "Summary", 4),
        "approved": _is_yes(_cell(row, headers, "Approve/Disapprove", 5))
        or str(_cell(row, headers, "Approve/Disapprove", 5)).strip().lower() == "approved",
        "published": _is_yes(_cell(row, headers, "Published", 6)),
    }


# ---------------------------------------------------------------------------
# Upserts
# ---------------------------------------------------------------------------
def get_or_create_site(session: Session, slug: str = "") -> Site:
    slug = (slug or DEFAULT_SITE_SLUG).strip()
    site = session.execute(select(Site).where(Site.slug == slug)).scalar_one_or_none()
    if site is None:
        site = Site(slug=slug, name=slug.replace("-", " ").title())
        session.add(site)
        session.commit()
        session.refresh(site)
    return site


def mirror_keyword(session: Session, *, keyword: str, volume: int = 0,
                   difficulty: float = 0.0, intent: str = "informational",
                   summary: str = "", generated: bool = False,
                   site_slug: str = "") -> Optional[KeywordLedger]:
    if not (keyword or "").strip():
        return None
    site = get_or_create_site(session, site_slug)
    row = upsert_keyword(session, site.id, keyword.strip(), intent=intent,
                         volume=volume, difficulty=difficulty,
                         research_snapshot={"summary": summary})
    # research_data's Generated=Yes means the brief was produced → briefed.
    if generated and row.status in ("researched", "approved", "queued"):
        row.status = "briefed"
        session.commit()
    return row


def mirror_brief(session: Session, *, keyword: str, brief_content: str = "",
                 faqs: str = "", sources: str = "", summary: str = "",
                 generated: bool = False,
                 site_slug: str = "") -> Optional[KeywordLedger]:
    if not (keyword or "").strip():
        return None
    site = get_or_create_site(session, site_slug)
    row = session.execute(
        select(KeywordLedger).where(
            KeywordLedger.site_id == site.id, KeywordLedger.keyword == keyword.strip())
    ).scalar_one_or_none()
    if row is None:
        row = upsert_keyword(session, site.id, keyword.strip())
    row.research_snapshot = {
        **(row.research_snapshot or {}),
        "brief": brief_content,
        "faqs": faqs,
        "sources": sources,
        "summary": summary,
    }
    if generated and row.status in ("researched", "approved", "queued"):
        row.status = "briefed"
    session.commit()
    session.refresh(row)
    return row


def mirror_article(session: Session, *, title: str, content: str = "",
                   faqs: str = "", quality_score: float = 0.0, summary: str = "",
                   approved: bool = False, published: bool = False,
                   site_slug: str = "") -> Optional[Article]:
    if not (title or "").strip():
        return None
    site = get_or_create_site(session, site_slug)
    status = "published" if published else ("approved" if approved else "generated")
    art = session.execute(
        select(Article).where(Article.site_id == site.id, Article.title == title.strip())
    ).scalars().first()
    if art is None:
        art = Article(site_id=site.id, title=title.strip())
        session.add(art)
    art.content_md = content or art.content_md
    art.scores = {**(art.scores or {}), "quality": quality_score}
    art.meta = {**(art.meta or {}), "faqs": faqs, "summary": summary}
    art.status = status
    session.commit()
    session.refresh(art)
    return art


# ---------------------------------------------------------------------------
# The dual-write hook (called from tools/sheet_tool after a Sheets append)
# ---------------------------------------------------------------------------
def mirror_sheet_append(worksheet_name: str, row_values: List[Any],
                        headers: Optional[List[str]] = None) -> bool:
    """Best-effort mirror of one appended Sheets row into Postgres.

    Returns True only if a mapped row was written. Unknown worksheets (or
    DUALWRITE_ENABLED=0) are a silent no-op. Never raises."""
    if not DUALWRITE_ENABLED:
        return False
    kind = SHEET_TARGETS.get((worksheet_name or "").strip().lower())
    if not kind or not row_values:
        return False
    try:
        init_db()
        session = get_session()
        try:
            if kind == "keyword":
                mirror_keyword(session, **map_research_row(row_values, headers))
            elif kind == "brief":
                mirror_brief(session, **map_brief_row(row_values, headers))
            elif kind == "article":
                mirror_article(session, **map_generated_post_row(row_values, headers))
            else:
                return False
            return True
        finally:
            session.close()
    except Exception as e:
        logger.warning(f"dual-write mirror failed for {worksheet_name} (non-fatal): {e}")
        return False


def verify_cutover(session: Session, site_slug: str = "") -> Dict[str, Any]:
    """Counts for a Sheets-vs-Postgres reconciliation check."""
    site = get_or_create_site(session, site_slug)
    keywords = session.execute(
        select(func.count()).select_from(KeywordLedger)
        .where(KeywordLedger.site_id == site.id)
    ).scalar_one()
    articles = session.execute(
        select(func.count()).select_from(Article).where(Article.site_id == site.id)
    ).scalar_one()
    return {"site": site.slug, "keywords": keywords, "articles": articles}
