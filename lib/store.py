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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import unquote, urlsplit

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from lib.db import (Article, AuditLog, CostLedger, KeywordLedger, Site,
                    get_session, init_db)
from lib.ledger import briefable_rows, upsert_keyword
from lib.site_env import is_shared_mode

logger = logging.getLogger(__name__)

DUALWRITE_ENABLED = os.environ.get("DUALWRITE_ENABLED", "1").strip().lower() not in (
    "0", "false", "no", "off",
)
DEFAULT_SITE_SLUG = os.environ.get("DEFAULT_SITE_SLUG") or "owaisabdullah-dev"
# Step 2 switch: when "postgres", read APIs below serve the pipeline; the
# default stays "sheets" until a clean drift report justifies the flip.
STORE_READ_SOURCE = os.environ.get("STORE_READ_SOURCE", "sheets").strip().lower()

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
    "Primary Keyword", "Secondary Keywords",
]
_BRIEF_HEADERS = [
    "Keyword/Topic", "Brief Content", "FAQs", "External Source Links",
    "Content Summary", "Generated", "Secondary Keywords",
]
_POST_HEADERS = [
    "Title", "Generated Content", "FAQs", "Quality Score", "Summary",
    "Approve/Disapprove", "Published", "Repurpose Bundle",
    "Video Script Seed", "Secondary Keywords",
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


# The sheet's "User Intent" cells are free prose ("Informational /
# Educational & Architectural Decision-Making (targeting AI Engineers…"),
# but keyword_ledger.intent is String(40) and the brief templates key off
# short tokens — SQLite ignored the length, Postgres enforces it. Map the
# prose to the template vocabulary by earliest marker (prose cells lead
# with their classification); the raw text is kept by callers in the
# research snapshot so nothing is lost.
_INTENT_MARKERS: tuple = tuple(
    (marker, token)
    for token, markers in (
        ("transactional", ("transactional", "purchase", "buy now",
                           "discount", "coupon", "pricing")),
        ("navigational", ("navigational", "navigation")),
        ("commercial", ("commercial", "comparison", "comparing", " vs ",
                        "versus", "evaluat")),
        ("informational", ("informational", "educational", "technical",
                           "research", "learn")),
    )
    for marker in markers
)


def _intent_token(raw: str) -> str:
    """One of informational/navigational/commercial/transactional — always
    short enough for the String(40) column, always a token the brief
    templates understand."""
    low = (raw or "").strip().lower()
    best_pos, best_token = -1, "informational"
    for marker, token in _INTENT_MARKERS:
        pos = low.find(marker)
        if pos != -1 and (best_pos == -1 or pos < best_pos):
            best_pos, best_token = pos, token
    return best_token


# ---------------------------------------------------------------------------
# Row mappers
# ---------------------------------------------------------------------------
def map_research_row(row: List[Any], headers: Optional[List[str]] = None) -> Dict[str, Any]:
    primary = _cell(row, headers, "Primary Keyword", 8)
    subject = _cell(row, headers, "Keyword/Topic", 0)
    raw_intent = _cell(row, headers, "User Intent", 3, default="informational")
    return {
        "keyword": primary or subject,
        "subject": subject,
        "primary_keyword": primary,
        "secondary_keywords": _cell(row, headers, "Secondary Keywords", 9),
        "volume": _to_int(_cell(row, headers, "Search Volume", 1)),
        "difficulty": _to_float(_cell(row, headers, "Difficulty", 2)),
        "intent": _intent_token(raw_intent),
        "intent_raw": raw_intent or "informational",
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
        "secondary_keywords": _cell(row, headers, "Secondary Keywords", 6),
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
        "secondary_keywords": _cell(row, headers, "Secondary Keywords", 9),
    }


# ---------------------------------------------------------------------------
# Upserts
# ---------------------------------------------------------------------------
def get_or_create_site(session: Session, slug: str = "") -> Site:
    slug = (slug or "").strip()
    if not slug:
        # TENANCY_MODE=shared means this process serves a platform DB with
        # several tenants (SaaS shape). A silent fallback to DEFAULT_SITE_SLUG
        # would attribute the row to the wrong tenant, so fail fast instead.
        if is_shared_mode():
            raise ValueError(
                "TENANCY_MODE=shared requires an explicit site_slug; "
                "refusing to fall back to the default tenant")
        slug = DEFAULT_SITE_SLUG
    site = session.execute(select(Site).where(Site.slug == slug)).scalar_one_or_none()
    if site is None:
        site = Site(slug=slug, name=slug.replace("-", " ").title())
        session.add(site)
        session.commit()
        session.refresh(site)
    return site


# keyword_ledger.keyword is String(300). sqlite tolerated longer cells,
# Postgres enforces the length — and a stray cell occasionally holds a
# whole article instead of a keyword (seen in ContentSpark_Keywords). Skip
# such cells loudly rather than truncate them into fake keywords.
MAX_KEYWORD_LEN = 300


def mirror_keyword(session: Session, *, keyword: str, volume: int = 0,
                   difficulty: float = 0.0, intent: str = "informational",
                   summary: str = "", generated: bool = False,
                   primary_keyword: str = "", secondary_keywords: str = "",
                   subject: str = "", site_slug: str = "",
                   intent_raw: str = "") -> Optional[KeywordLedger]:
    keyword = (keyword or "").strip()
    if not keyword:
        return None
    if len(keyword) > MAX_KEYWORD_LEN:
        logger.warning(f"mirror_keyword: skipping {len(keyword)}-char cell "
                       f"(keyword column holds {MAX_KEYWORD_LEN})")
        return None
    site = get_or_create_site(session, site_slug)
    row = upsert_keyword(session, site.id, keyword, intent=intent,
                         volume=volume, difficulty=difficulty,
                         research_snapshot={
                             "summary": summary,
                             # The topic the research was actually about, kept
                             # separate from the keyword it is optimized for
                             # (they differ on rows that carry a YT
                             # transcript or a long title-style topic).
                             "subject": subject,
                             # Keyword targets the operator supplied on the
                             # keyword sheet. They ride in research_snapshot
                             # (JSON, so no schema migration) and are read back
                             # by get_next_brief_task -> brief -> generation.
                             "primary_keyword": primary_keyword,
                             "secondary_keywords": secondary_keywords,
                             # The sheet's full-sentence User Intent cell, kept
                             # beside the tokenized intent column.
                             "intent_raw": intent_raw,
                         })
    # research_data's Generated=Yes means the brief was produced -> briefed.
    if generated and row.status in ("researched", "approved", "queued"):
        row.status = "briefed"
        session.commit()
    return row


def mirror_brief(session: Session, *, keyword: str, brief_content: str = "",
                 faqs: str = "", sources: str = "", summary: str = "",
                 generated: bool = False, secondary_keywords: str = "",
                 site_slug: str = "") -> Optional[KeywordLedger]:
    keyword = (keyword or "").strip()
    if not keyword:
        return None
    if len(keyword) > MAX_KEYWORD_LEN:
        logger.warning(f"mirror_brief: skipping {len(keyword)}-char cell "
                       f"(keyword column holds {MAX_KEYWORD_LEN})")
        return None
    site = get_or_create_site(session, site_slug)
    row = session.execute(
        select(KeywordLedger).where(
            KeywordLedger.site_id == site.id, KeywordLedger.keyword == keyword)
    ).scalar_one_or_none()
    if row is None:
        row = upsert_keyword(session, site.id, keyword)
    row.research_snapshot = {
        **(row.research_snapshot or {}),
        "brief": brief_content,
        "faqs": faqs,
        "sources": sources,
        "summary": summary,
        "secondary_keywords": secondary_keywords,
    }
    if generated and row.status in ("researched", "approved", "queued"):
        row.status = "briefed"
    session.commit()
    session.refresh(row)
    return row


def mirror_article(session: Session, *, title: str, content: str = "",
                   faqs: str = "", quality_score: float = 0.0, summary: str = "",
                   approved: bool = False, published: bool = False,
                   secondary_keywords: str = "",
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
    if secondary_keywords:
        # Carried so the publish step can store the operator's keyword targets
        # on the delivered document (content_briefs is gone by then).
        art.meta = {**art.meta, "secondary_keywords": secondary_keywords}
    if status == "published":
        art.status = "published"
    elif not (art.meta or {}).get("published_url"):
        # A recorded live URL outranks a lagging "Published: No" cell — the
        # operator sometimes ticks the generated_posts flag late while
        # published_posts already carries the URL. Without this rule the two
        # sheets fight over the status on every backfill/dual-write pass.
        art.status = status
    session.commit()
    session.refresh(art)
    return art


# ---------------------------------------------------------------------------
# The dual-write hook (called from tools/sheet_tool after a Sheets append)
# ---------------------------------------------------------------------------
def log_usage_event(kind: str, payload: dict) -> bool:
    """Best-effort Postgres mirror for one usage-log row (console Logs screen).

    The model/image usage worksheets are Sheets-only (not in SHEET_TARGETS),
    so a SHEETS_ENABLED=0 instance would silently lose every row. Callers
    append to Sheets as before AND call this; site #1 keeps both surfaces in
    sync, instance 2 gets audit rows only. Writes audit_log
    action="usage.<kind>". Never raises."""
    if not str(kind or "").strip():
        return False
    try:
        init_db()
        session = get_session()
        try:
            session.add(AuditLog(action=f"usage.{str(kind).strip()}",
                                 payload=dict(payload or {})))
            session.commit()
            return True
        finally:
            session.close()
    except Exception as e:
        logger.warning(f"usage mirror failed for {kind} (non-fatal): {e}")
        return False


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


# ---------------------------------------------------------------------------
# Extended backfill — the sheets beyond research/briefs/posts
# (published_posts, usage logs, image_logs, review, performance, audit,
# freshness_sweep, and the separate ContentSpark_Keywords queue).
# Every import is idempotent: the row's identity rides in payload/detail
# under "sheet_ref", and callers preload existing refs so a re-run
# inserts nothing twice.
# ---------------------------------------------------------------------------
_SHEET_TS_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M")


def _sheet_ts(raw: Any) -> Optional[datetime]:
    """Sheet timestamps are UTC strings ("2026-10-18 07:54:33 UTC"; older
    rows lack seconds). Unparseable -> None (created_at falls back to now,
    the row still imports)."""
    text = str(raw or "").strip().removesuffix(" UTC").strip()
    for fmt in _SHEET_TS_FORMATS:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def mirror_sheet_audit(session: Session, *, action: str, payload: Dict[str, Any],
                       ts_raw: Any = "", seen: Optional[set] = None,
                       article_id: Optional[int] = None,
                       site_id: Optional[int] = None) -> bool:
    """One historical sheet row -> an audit_log row, idempotent on
    payload["sheet_ref"]. Never commits (the backfill commits per
    worksheet); `seen` is the preloaded set of refs already imported for
    this action — pass it for bulk imports (one read, not one per row).
    Without it the idempotency contract still holds via a per-row query."""
    ref = str((payload or {}).get("sheet_ref") or "")
    if not ref:
        return False
    if seen is not None:
        if ref in seen:
            return False
        seen.add(ref)
    else:
        session.flush()
        if ref in existing_sheet_refs(session, action):
            return False
    ts = _sheet_ts(ts_raw)
    session.add(AuditLog(action=action, payload=payload, article_id=article_id,
                         site_id=site_id, **({"created_at": ts} if ts else {})))
    return True


def existing_sheet_refs(session: Session, action: str) -> set:
    """Every payload["sheet_ref"] already imported under an audit action."""
    rows = session.execute(
        select(AuditLog.payload).where(AuditLog.action == action)).scalars()
    return {str(p.get("sheet_ref")) for p in rows if p and p.get("sheet_ref")}


def mirror_sheet_cost(session: Session, *, kind: str, amount_usd: float,
                      detail: Dict[str, Any], article_id: int,
                      ts_raw: Any = "", seen: Optional[set] = None) -> bool:
    """One historical cost row (image_logs) -> cost_ledger, idempotent on
    detail["sheet_ref"]. Never commits; same `seen` convention as
    mirror_sheet_audit (fallback query when no set is passed)."""
    ref = str((detail or {}).get("sheet_ref") or "")
    if not ref:
        return False
    if seen is not None:
        if ref in seen:
            return False
        seen.add(ref)
    else:
        session.flush()
        if ref in existing_cost_refs(session, kind):
            return False
    ts = _sheet_ts(ts_raw)
    session.add(CostLedger(article_id=article_id, kind=kind,
                           amount_usd=float(amount_usd or 0.0), detail=detail,
                           **({"created_at": ts} if ts else {})))
    return True


def existing_cost_refs(session: Session, kind: str) -> set:
    """Every detail["sheet_ref"] already imported under a cost kind."""
    rows = session.execute(
        select(CostLedger.detail).where(CostLedger.kind == kind)).scalars()
    return {str(d.get("sheet_ref")) for d in rows if d and d.get("sheet_ref")}


def mirror_published_post(session: Session, *, title: str, url: str,
                          site_slug: str = "") -> tuple[Optional[Article], bool]:
    """published_posts row -> the article's published URL.

    Matches by title on the site; a match gets status=published, a slug
    derived from the URL path (when it has none), and
    meta.published_url. A title with no article row (posts older than the
    ledger) becomes a stub published article carrying the URL — the
    sitemap/decay tooling needs the full URL inventory, not just the 50
    articles the store knows content for.

    Returns (article, changed) — changed is False when the row already
    carried this URL, so a re-run reports 0 imported, not a re-count."""
    title = (title or "").strip()
    url = (url or "").strip()
    if not title or not url:
        return None, False
    site = get_or_create_site(session, site_slug)
    art = session.execute(
        select(Article).where(Article.site_id == site.id, Article.title == title)
    ).scalars().first()
    slug = _slug_from_url(url)
    if art is None:
        art = Article(site_id=site.id, title=title, slug=slug,
                      status="published",
                      meta={"published_url": url, "source": "sheet-backfill"})
        session.add(art)
        session.commit()
        session.refresh(art)
        return art, True
    changed = False
    if (art.meta or {}).get("published_url") != url:
        art.meta = {**(art.meta or {}), "published_url": url}
        changed = True
    if art.status != "published":
        art.status = "published"
        changed = True
    if not art.slug and slug:
        art.slug = slug
        changed = True
    if changed:
        session.commit()
        session.refresh(art)
    return art, changed


def _slug_from_url(url: str) -> str:
    """https://x.dev/blog/my-post/ -> 'my-post' (unquoted, last path seg)."""
    path = unquote(urlsplit(url).path.strip("/"))
    if path.startswith("blog/"):
        path = path[5:]
    return path.split("/")[-1] if "/" in path else path


def mirror_keyword_queue(session: Session, *, keyword: str, primary: str = "",
                         secondary: str = "", status: str = "",
                         site_slug: str = "") -> Optional[KeywordLedger]:
    """ContentSpark_Keywords queue row -> keyword_ledger.

    CREATE-ONLY for status: an existing row (researched/briefed from
    research_data) keeps whatever status it earned — the queue sheet only
    carries claim state, which the ledger owns natively now. The only
    write to an existing row is an additive snapshot merge (primary /
    secondary keyword targets, never a clobber), so this handler runs in
    any order relative to research_data. New rows map sheet status:
    available/claimed -> queued, briefed -> briefed."""
    keyword = (keyword or "").strip()
    if not keyword:
        return None, False
    if len(keyword) > MAX_KEYWORD_LEN:
        logger.warning(f"mirror_keyword_queue: skipping {len(keyword)}-char "
                       f"cell (keyword column holds {MAX_KEYWORD_LEN})")
        return None, False
    site = get_or_create_site(session, site_slug)
    existing = session.execute(
        select(KeywordLedger).where(KeywordLedger.site_id == site.id,
                                    KeywordLedger.keyword == keyword)
    ).scalar_one_or_none()
    if existing is not None:
        snap = dict(existing.research_snapshot or {})
        changed = False
        if primary.strip() and not snap.get("primary_keyword"):
            snap["primary_keyword"] = primary.strip()
            changed = True
        if secondary.strip() and not snap.get("secondary_keywords"):
            snap["secondary_keywords"] = secondary.strip()
            changed = True
        if changed:
            existing.research_snapshot = snap
            session.commit()
        return existing, changed
    row = upsert_keyword(session, site.id, keyword, research_snapshot={
        "primary_keyword": (primary or "").strip(),
        "secondary_keywords": (secondary or "").strip(),
        "source": "keywords-sheet",
    })
    target = {"available": "queued", "claimed": "queued",
              "briefed": "briefed"}.get((status or "").strip().lower())
    if target and target != row.status:
        row.status = target
        session.commit()
        session.refresh(row)
    return row, True


# --- historical-row mappers (dict in, payload with a stable sheet_ref out) --
def map_usage_log_row(rec: Dict[str, Any]) -> Dict[str, Any]:
    """usage logs -> audit usage.model (the model-performance history)."""
    ts = str(rec.get("Timestamp") or "").strip()
    return {
        "sheet_ref": "usage:" + "|".join([ts, str(rec.get("Model") or ""),
                                          str(rec.get("Agent") or ""),
                                          str(rec.get("Stage") or "")]),
        "timestamp": ts,
        "model": str(rec.get("Model") or ""),
        "agent": str(rec.get("Agent") or ""),
        "stage": str(rec.get("Stage") or ""),
        "status": str(rec.get("Status") or ""),
        "latency_s": str(rec.get("Latency (s)") or ""),
        "source": "sheet-backfill",
    }


def map_image_log_row(rec: Dict[str, Any]) -> Dict[str, Any]:
    """image_logs -> cost_ledger detail (or audit usage.image when no
    article matches)."""
    ts = str(rec.get("Timestamp") or "").strip()
    return {
        "sheet_ref": "image:" + "|".join([ts, str(rec.get("Model") or ""),
                                          str(rec.get("Slot") or ""),
                                          str(rec.get("Subject") or "")]),
        "timestamp": ts,
        "model": str(rec.get("Model") or ""),
        "stage": str(rec.get("Stage") or ""),
        "subject": str(rec.get("Subject") or ""),
        "status": str(rec.get("Status") or ""),
        "reference": str(rec.get("Reference") or ""),
        "latency_s": str(rec.get("Latency (s)") or ""),
        "latency_ms": str(rec.get("Latency (ms)") or ""),
        "detail": str(rec.get("Detail") or ""),
        "slot": str(rec.get("Slot") or ""),
        "prompt": str(rec.get("Prompt") or ""),
        "cost_usd": str(rec.get("Cost (USD)") or ""),
        "source": "sheet-backfill",
    }


def map_review_row(rec: Dict[str, Any]) -> Dict[str, Any]:
    ts = str(rec.get("Timestamp") or "").strip()
    return {
        "sheet_ref": "review:" + "|".join([ts, str(rec.get("Title") or ""),
                                           str(rec.get("Status") or "")]),
        "timestamp": ts,
        "title": str(rec.get("Title") or ""),
        "review_status": str(rec.get("Status") or ""),
        "quality_score": str(rec.get("Quality Score") or ""),
        "summary": str(rec.get("Summary") or ""),
        "reason": str(rec.get("Reason") or ""),
        "source": "sheet-backfill",
    }


def map_performance_row(rec: Dict[str, Any]) -> Dict[str, Any]:
    ts = str(rec.get("Timestamp") or "").strip()
    return {
        "sheet_ref": "performance:" + "|".join([ts, str(rec.get("URL") or "")]),
        "timestamp": ts,
        "title": str(rec.get("Title") or ""),
        "url": str(rec.get("URL") or ""),
        "impressions": str(rec.get("Impressions") or ""),
        "clicks": str(rec.get("Clicks") or ""),
        "ctr": str(rec.get("CTR") or ""),
        "position": str(rec.get("Average Position") or ""),
        "finding": str(rec.get("Finding") or ""),
        "suggested_edit": str(rec.get("Suggested Edit") or ""),
        "status": str(rec.get("Status") or ""),
        "source": "sheet-backfill",
    }


def map_claims_audit_row(rec: Dict[str, Any]) -> Dict[str, Any]:
    ts = str(rec.get("Timestamp") or "").strip()
    return {
        "sheet_ref": "claims:" + "|".join([ts, str(rec.get("Title") or "")]),
        "timestamp": ts,
        "title": str(rec.get("Title") or ""),
        "keyword": str(rec.get("Keyword/Topic") or ""),
        "quality_score": str(rec.get("Quality Score") or ""),
        "notes": str(rec.get("Claims Notes") or ""),
        "source": "sheet-backfill",
    }


def map_freshness_row(rec: Dict[str, Any]) -> Dict[str, Any]:
    ts = str(rec.get("Timestamp") or "").strip()
    return {
        "sheet_ref": "freshness:" + "|".join([ts, str(rec.get("Title") or "")]),
        "timestamp": ts,
        "title": str(rec.get("Title") or ""),
        "status": str(rec.get("Status") or ""),
        "reason": str(rec.get("Reason") or ""),
        "suggested_edit": str(rec.get("Suggested Edit") or ""),
        "source": "sheet-backfill",
    }


def title_article_index(session: Session, site_id: int) -> Dict[str, int]:
    """title -> article_id for one site (historical rows link by title)."""
    rows = session.execute(
        select(Article.id, Article.title).where(Article.site_id == site_id)
    ).all()
    return {(t or "").strip(): i for i, t in rows}


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


# ---------------------------------------------------------------------------
# Step 2 — retire Sheets reads (read API; gated by STORE_READ_SOURCE)
# ---------------------------------------------------------------------------
def read_source() -> str:
    return STORE_READ_SOURCE


def use_postgres_reads() -> bool:
    return STORE_READ_SOURCE == "postgres"


def list_briefable(site_slug: str = "", limit: int = 50) -> List[Dict[str, Any]]:
    """Approved/queued ledger rows — the brief queue, from Postgres."""
    init_db()
    session = get_session()
    try:
        site = get_or_create_site(session, site_slug)
        return [
            {"keyword": r.keyword, "intent": r.intent, "status": r.status,
             "cluster_id": r.cluster_id, "priority_score": r.priority_score}
            for r in briefable_rows(session, site.id, limit=limit)
        ]
    finally:
        session.close()


def list_generated_posts(site_slug: str = "", published: Optional[bool] = None) -> List[Dict[str, Any]]:
    """Article rows (optionally filtered by published status), from Postgres."""
    init_db()
    session = get_session()
    try:
        site = get_or_create_site(session, site_slug)
        q = select(Article).where(Article.site_id == site.id)
        if published is True:
            q = q.where(Article.status == "published")
        elif published is False:
            q = q.where(Article.status != "published")
        return [
            {"id": a.id, "title": a.title, "slug": a.slug, "status": a.status,
             "quality": (a.scores or {}).get("quality")}
            for a in session.execute(q).scalars()
        ]
    finally:
        session.close()


def find_generated_post(title: str, site_slug: str = "") -> Optional[Dict[str, Any]]:
    init_db()
    session = get_session()
    try:
        site = get_or_create_site(session, site_slug)
        art = session.execute(
            select(Article).where(Article.site_id == site.id, Article.title == (title or "").strip())
        ).scalars().first()
        if art is None:
            return None
        return {"id": art.id, "title": art.title, "status": art.status,
                "markdown": art.content_md, "scores": art.scores or {}}
    finally:
        session.close()


def keyword_set(site_slug: str = "") -> set:
    init_db()
    session = get_session()
    try:
        site = get_or_create_site(session, site_slug)
        return {r for (r,) in session.execute(
            select(KeywordLedger.keyword).where(KeywordLedger.site_id == site.id)
        )}
    finally:
        session.close()


def article_title_set(site_slug: str = "") -> set:
    init_db()
    session = get_session()
    try:
        site = get_or_create_site(session, site_slug)
        return {r for (r,) in session.execute(
            select(Article.title).where(Article.site_id == site.id)
        )}
    finally:
        session.close()


def drift_report(sheets_keywords: set, sheets_titles: set, site_slug: str = "") -> Dict[str, Any]:
    """Compare the two stores' key sets. Empty lists on both sides == in sync."""
    pg_kw = keyword_set(site_slug)
    pg_titles = article_title_set(site_slug)
    return {
        "site": site_slug or DEFAULT_SITE_SLUG,
        "keywords": {
            "sheets": len(sheets_keywords), "postgres": len(pg_kw),
            "missing_in_postgres": sorted(sheets_keywords - pg_kw)[:50],
            "missing_in_sheets": sorted(pg_kw - sheets_keywords)[:50],
        },
        "articles": {
            "sheets": len(sheets_titles), "postgres": len(pg_titles),
            "missing_in_postgres": sorted(sheets_titles - pg_titles)[:50],
            "missing_in_sheets": sorted(pg_titles - sheets_titles)[:50],
        },
    }
