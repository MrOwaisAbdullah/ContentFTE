"""§5.12 shared article service — the canonical operations behind BOTH the
REST SDK routes (`sdk/server.py`) and the MCP tools (`mcp_server/server.py`).

Order of layers (per plan): service -> API -> MCP. MCP never touches the DB
directly; it calls the same functions the API exposes, so the API contract is
the single source of truth and behavior can't drift between the two surfaces.

All functions are pure DB/HTTP — no LLM calls, model router untouched.
Errors are returned as dicts {"error": str, "next": str} (actionable).
"""
from __future__ import annotations

import json
from typing import Any

from slugify import slugify
from sqlalchemy import select

from lib import custom_site
from lib.db import Article, Article as ArticleModel, AuditLog, Site, get_session, init_db
from lib.cost_ledger import finalize
from lib.ledger import INTENT_VALUE, briefable_rows, upsert_keyword


def _err(message: str, nxt: str = "") -> dict:
    return {"error": message, **({"next": nxt} if nxt else {})}


def _resolve_slug(art: ArticleModel) -> str:
    """Article slug, derived from the title when the row never got one."""
    existing = (art.slug or "").strip()
    if existing:
        return existing
    return slugify(art.title or "")[:80] or "untitled"


def _parse_faqs(raw: Any) -> list[dict] | None:
    """`meta.faqs` arrives as a JSON string (sheet mirror) or an already-decoded
    list; normalize to [{question, answer}, ...] or None. Never raises."""
    if not raw:
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return None
    if not isinstance(raw, list):
        return None
    items = [f for f in raw if isinstance(f, dict) and f.get("question") and f.get("answer")]
    return items or None


def _iso(dt: Any) -> str | None:
    return dt.isoformat() if dt else None


def _site_by_slug(s, slug: str) -> Site | None:
    return s.execute(select(Site).where(Site.slug == slug)).scalar_one_or_none()


def init() -> None:
    init_db()


def list_sites() -> dict:
    init_db()
    s = get_session()
    try:
        sites = [{"id": r.id, "slug": r.slug, "name": r.name, "site_type": r.site_type,
                  "base_url": r.base_url, "publish_mode": r.publish_mode}
                 for r in s.execute(select(Site)).scalars()]
        return {"sites": sites, "count": len(sites)}
    finally:
        s.close()


def upsert_site(slug: str, name: str = "", site_type: str = "custom",
                base_url: str = "") -> dict:
    init_db()
    s = get_session()
    try:
        site = _site_by_slug(s, slug)
        created = False
        if site is None:
            site = Site(slug=slug, name=name or slug.title(), site_type=site_type,
                        base_url=base_url)
            s.add(site)
            s.commit()
            s.refresh(site)
            created = True
        return {"id": site.id, "slug": site.slug, "created": created}
    finally:
        s.close()


def get_brief(site_slug: str) -> dict:
    """§5.16 — briefs pull ONLY from approved/queued rows, highest priority first."""
    init_db()
    s = get_session()
    try:
        site = _site_by_slug(s, site_slug)
        if site is None:
            return _err(f"site '{site_slug}' not found", "run list_sites for valid slugs")
        rows = briefable_rows(s, site.id, limit=1)
        if not rows:
            return {"status": "empty",
                    "hint": "no approved/queued keywords — approve a ledger row first (§5.16)"}
        r = rows[0]
        return {"keyword": r.keyword, "intent": r.intent, "volume": r.volume,
                "difficulty": r.difficulty, "priority_score": r.priority_score,
                "intent_value": INTENT_VALUE.get((r.intent or "").lower(), 1.0),
                "research_snapshot": r.research_snapshot,
                "ledger_id": r.id, "status": r.status}
    finally:
        s.close()


def submit_article(site_slug: str, keyword: str = "", brief: dict | None = None) -> dict:
    """Create an article in 'briefed' state. Idempotent per (site, keyword).

    §5.16 lineage: when a keyword is given, the article is bound to its ledger
    row (resolved or created), so "zero articles without a keyword row" holds
    for anything submitted through the SDK/MCP."""
    init_db()
    s = get_session()
    try:
        site = _site_by_slug(s, site_slug)
        if site is None:
            site = Site(slug=site_slug, name=site_slug.title())
            s.add(site)
            s.commit()
            s.refresh(site)
        title = (brief or {}).get("title") or keyword or "Untitled"
        existing = s.execute(
            select(ArticleModel).where(ArticleModel.site_id == site.id,
                                       ArticleModel.title == title)
        ).scalars().first()
        if existing is not None:
            return {"id": existing.id, "status": existing.status, "deduplicated": True,
                    "event": "article.ready"}
        keyword_id = None
        if (keyword or "").strip():
            kw_row = upsert_keyword(s, site.id, keyword.strip())
            keyword_id = kw_row.id
        art = ArticleModel(site_id=site.id, keyword_id=keyword_id, title=title,
                           status="briefed",
                           meta={"brief": brief or {}, "keyword": keyword})
        s.add(art)
        s.flush()
        s.add(AuditLog(article_id=art.id, site_id=site.id, action="article.submit",
                       payload={"keyword": keyword, "title": title,
                                "keyword_id": keyword_id}))
        s.commit()
        s.refresh(art)
        return {"id": art.id, "status": art.status, "event": "article.ready",
                "keyword_id": keyword_id}
    finally:
        s.close()


def get_article(article_id: int, include_content: bool = False) -> dict:
    init_db()
    s = get_session()
    try:
        art = s.get(ArticleModel, article_id)
        if art is None:
            return _err(f"article {article_id} not found", "run generate_article first")
        data: dict[str, Any] = {"id": art.id, "site_id": art.site_id, "title": art.title,
                                "slug": art.slug, "status": art.status,
                                "scores": art.scores or {}, "cost_usd": art.cost_usd,
                                "keyword_id": art.keyword_id}
        if include_content:
            meta = art.meta or {}
            brief = meta.get("brief") if isinstance(meta.get("brief"), dict) else {}
            slug = _resolve_slug(art)
            base = ((art.site.base_url if art.site else "") or "").strip().rstrip("/")
            url = f"{base}/{slug}" if base else ""
            payload = custom_site.build_delivery_payload(
                title=art.title or slug,
                markdown=art.content_md or "",
                meta_description=str(brief.get("description") or meta.get("summary") or ""),
                slug=slug,
                url=url,
                faqs=_parse_faqs(meta.get("faqs") or brief.get("faqs")),
                date_published=_iso(art.created_at),
                date_modified=_iso(art.published_at or art.created_at),
            )
            if not payload.get("html") and art.content_html:
                payload["html"] = art.content_html
            data.update(payload)
            data["slug"] = slug
            data["meta"] = meta
        return data
    finally:
        s.close()


def approve_article(article_id: int, approved: bool = True, note: str = "",
                    via: str = "api") -> dict:
    init_db()
    s = get_session()
    try:
        art = s.get(ArticleModel, article_id)
        if art is None:
            return _err(f"article {article_id} not found", "run generate_article first")
        art.status = "approved" if approved else "needs_review"
        s.add(AuditLog(article_id=art.id, site_id=art.site_id,
                       action="article.approve" if approved else "article.needs_review",
                       payload={"note": note, "via": via}))
        s.commit()
        return {"id": art.id, "status": art.status,
                "event": "article.published" if approved else "article.needs_review"}
    finally:
        s.close()


def publish_article(article_id: int, mode: str = "draft", via: str = "api") -> dict:
    """Publish decision (§5.11 draft default). Requires approved status."""
    init_db()
    s = get_session()
    try:
        art = s.get(ArticleModel, article_id)
        if art is None:
            return _err(f"article {article_id} not found", "run generate_article first")
        if art.status not in ("approved", "published"):
            return _err(
                f"article {article_id} is '{art.status}' — publish requires 'approved'",
                "gate: overall >=90 and every sub-score >=80, then POST /sdk/v1/articles/{id}/approve")
        art.status = "published"
        s.add(AuditLog(article_id=art.id, site_id=art.site_id, action="article.publish",
                       payload={"mode": mode, "via": via}))
        # §5.10-6 finalize the per-post cost ledger at publish.
        totals = finalize(s, art.id)
        art.cost_usd = totals["total_usd"]
        s.commit()
        return {"id": art.id, "status": art.status, "mode": mode,
                "cost_usd": totals["total_usd"], "event": "article.published"}
    finally:
        s.close()


def get_images(article_id: int) -> dict:
    data = get_article(article_id, include_content=True)
    if "error" in data:
        return data
    images = (data.get("meta") or {}).get("images", [])
    return {"images": images, "count": len(images)}


def site_health(site_slug: str) -> dict:
    init_db()
    s = get_session()
    try:
        site = _site_by_slug(s, site_slug)
        if site is None:
            return _err(f"site '{site_slug}' not found", "run list_sites for valid slugs")
        briefable = len(briefable_rows(s, site.id, limit=50))
        published = len(s.execute(
            select(Article).where(Article.site_id == site.id,
                                  Article.status == "published")).scalars().all())
        import os
        wp_ok = bool(os.environ.get("WP_BASE_URL") and os.environ.get("WP_USERNAME"))
        checks = [
            "keyword ledger: OK" if briefable > 0 else
            "keyword ledger: EMPTY queue — research/approve keywords (§5.16)",
            "WordPress config: OK" if wp_ok else
            "WordPress config: missing WP_BASE_URL/WP_USERNAME/WP_APP_PASSWORD",
        ]
        return {"site": site.slug, "ok": briefable > 0,
                "ledger": {"briefable": briefable, "published": published},
                "wp_configured": wp_ok, "checks": checks}
    finally:
        s.close()
