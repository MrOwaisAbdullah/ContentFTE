"""§5.12 shared article service — the canonical operations behind BOTH the
REST SDK routes (`sdk/server.py`) and the MCP tools (`mcp_server/server.py`).

Order of layers (per plan): service -> API -> MCP. MCP never touches the DB
directly; it calls the same functions the API exposes, so the API contract is
the single source of truth and behavior can't drift between the two surfaces.

All functions are pure DB/HTTP except generate_content (§5.5): it is the
one op that runs a model, and only via an injectable `generate_fn` — tests
inject fakes, production lazily loads blog_agent.generation (shared
content_generator_agent through run_with_fallback). publish_article also
makes HTTP calls for site_type="wordpress" sites (the §5.11 WordPress
push: post + meta + schema + taxonomy + media, best-effort fail-open —
no model calls, never rolls back the status flip). The model router is
consumed read-only, never edited (routing refactor is the last TASKS item).
Errors are returned as dicts {"error": str, "next": str} (actionable).
"""
from __future__ import annotations

import copy
import json
import logging
import os
import re
import shutil
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from slugify import slugify
from sqlalchemy import delete, func, select

from lib import custom_site
from lib import generation
from lib.db import (ApiKey, Article, Article as ArticleModel, AuditLog, BrainEntry,
                    BrandProfile, CostLedger, KeywordLedger, ReviewFeedback,
                    ShareOfVoice, Site, TavilyUsage, get_session, init_db)
from lib.cost_ledger import finalize, record_cost, usage_cost
from lib import quality_gate
from lib.ledger import INTENT_VALUE, briefable_rows, set_status, upsert_keyword
from lib.secrets_redact import merge_settings, redact_settings
from lib.safe_fetch import safe_get
from lib.store import article_scores
from lib.taxonomy import derive_taxonomy

# `logger` was referenced (run_instant_pipeline) but never defined, so every
# failure in that background path raised NameError instead of logging (plan ENG-01).
logger = logging.getLogger(__name__)


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
    """ISO-8601 with an explicit offset. Every stored timestamp is UTC, but SQLite hands back
    NAIVE datetimes (Postgres hands back aware ones), so the same row used to serialize as
    '...T17:30:50' on one backend and '...T17:30:50+00:00' on the other -- and structured data
    (datePublished/dateModified) needs the offset."""
    if not dt:
        return None
    if isinstance(dt, datetime) and dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _modified_iso(art: ArticleModel) -> str | None:
    """`dateModified` for structured data: the last SUBSTANTIVE edit (meta.modified_at), never
    earlier than the publish date. It used to be the publish date itself, so freshness was never
    signalled; and it is only bumped for real content changes (lib/freshness.py)."""
    from lib import freshness
    return freshness.effective_modified(art.meta, _iso(art.published_at), _iso(art.created_at))


def _schema_extra(art: ArticleModel, meta: dict, brief: dict) -> dict:
    """Optional Article JSON-LD enrichment from REAL data only: the site's configured author and
    publisher (Site.settings["identity"]), the brief's description/keywords, the word count and a
    remote featured-image URL when one is recorded. Missing pieces are omitted, never invented."""
    from lib import geo
    site = art.site
    ident = geo.identity_from_settings(
        site.settings if site else None, site.name if site else "",
        (site.base_url if site else "") or "")
    image = None
    for row in (meta.get("images") or []):
        if isinstance(row, dict) and str(row.get("url") or "").startswith(("http://", "https://")):
            image = {"url": row["url"], "caption": str(row.get("alt") or "")}
            if row.get("slot") == "featured":
                break
    kws = [_focus_keyphrase(meta, brief)] + [
        k.strip() for k in str(brief.get("secondary_keywords") or "").replace(";", ",").split(",")
        if k.strip()]
    return {
        "author": ident["author"],
        "publisher": ident["publisher"],
        "image": image,
        "description": str(brief.get("description") or meta.get("summary") or ""),
        "keywords": [k for k in kws if k],
        "word_count": len((art.content_md or "").split()) or None,
    }


def _cost_map(s, article_ids: list[int]) -> dict[int, float]:
    """Per-article spend, derived from cost_ledger with one grouped SUM —
    articles no longer denormalize a cost_usd copy."""
    if not article_ids:
        return {}
    rows = s.execute(
        select(CostLedger.article_id, func.sum(CostLedger.amount_usd))
        .where(CostLedger.article_id.in_(article_ids))
        .group_by(CostLedger.article_id)
    ).all()
    return {int(i): float(t or 0.0) for i, t in rows}


def _site_by_slug(s, slug: str) -> Site | None:
    return s.execute(select(Site).where(Site.slug == slug)).scalar_one_or_none()


def init() -> None:
    init_db()


def _site_row(r: Site) -> dict:
    # Secrets (WP application password, IndexNow/Bing keys, Discord webhook)
    # never leave the engine: this payload goes to every API client, the MCP
    # tool (i.e. into LLM context) and the browser-facing console. `secrets_set`
    # says which exist so UIs can show "saved" without the value (plan SEC-04).
    safe_settings, secrets_set = redact_settings(r.settings)
    return {"id": r.id, "slug": r.slug, "name": r.name, "site_type": r.site_type,
            "base_url": r.base_url,
            # publish_mode rides in settings (the column it used to
            # occupy was never written — always the default).
            "publish_mode": str((r.settings or {}).get("publish_mode") or "draft"),
            "settings": safe_settings, "secrets_set": secrets_set,
            "has_key": bool(r.api_key), "created_at": _iso(r.created_at)}


def list_sites() -> dict:
    init_db()
    s = get_session()
    try:
        active = dict(s.execute(
            select(ApiKey.site_id, func.count()).where(ApiKey.revoked_at.is_(None))
            .group_by(ApiKey.site_id)).all())
        sites = []
        for r in s.execute(select(Site)).scalars():
            row = _site_row(r)
            row["active_keys"] = int(active.get(r.id, 0))
            row["has_key"] = bool(row["has_key"]) or row["active_keys"] > 0
            sites.append(row)
        return {"sites": sites, "count": len(sites)}
    finally:
        s.close()


def get_search_console_status() -> dict:
    """Per-site Search Console connectivity (console Sites screen + MCP).

    One sites.list call answers for every site on the instance: the
    property is resolved per site (settings override, else base_url + "/")
    and matched against the properties the instance's GOOGLE_CREDENTIALS
    service account can actually access. Adding that one service-account
    email as a user on each property (Search Console -> Settings ->
    Users and permissions; Restricted is enough for read-only) is the only
    manual step this cannot do. `connected` is tri-state: true / false /
    null when the check itself couldn't run (no credentials, API error)."""
    init_db()
    session = get_session()
    try:
        sites = session.execute(select(Site)).scalars().all()
    finally:
        session.close()
    from lib import search_console

    creds_raw = os.environ.get("GOOGLE_CREDENTIALS", "").strip()
    sa_email = ""
    if creds_raw:
        try:
            sa_email = json.loads(creds_raw).get("client_email", "")
        except Exception:
            sa_email = ""
    entries = search_console.list_accessible_properties() if creds_raw else None

    out_sites: list[dict] = []
    for site in sites:
        prop = search_console.resolve_site_property(site.base_url, site.settings)
        row: dict = {"slug": site.slug, "base_url": site.base_url,
                     "property": prop}
        if not prop:
            row.update(connected=False,
                       reason="not configured (no base_url, no "
                              "settings.search_console_site_url)")
        elif not creds_raw:
            row.update(connected=False,
                       reason="no service account credentials "
                              "(GOOGLE_CREDENTIALS not set)")
        elif entries is None:
            row.update(connected=None,
                       reason="could not list properties "
                              "(Search Console API unreachable)")
        else:
            hit = search_console.match_property(prop, entries)
            is_connected = hit is not None
            row.update(connected=is_connected,
                       permission_level=(hit or {}).get("permission_level", ""))
            if is_connected:
                perf = search_console.get_site_totals(days=28, site_url=prop)
                if perf:
                    row["metrics_28d"] = {
                        "clicks": perf.get("clicks", 0),
                        "impressions": perf.get("impressions", 0),
                        "ctr": round(perf.get("ctr", 0.0) * 100, 2),
                        "position": round(perf.get("position", 0.0), 1),
                    }
        out_sites.append(row)
    return {
        "sites": out_sites,
        "service_account_email": sa_email,
        "credentials": bool(creds_raw),
        "properties_visible": len(entries) if entries is not None else None,
        "visible": entries if entries is not None else [],
    }


def upsert_site(slug: str, name: str = "", site_type: str = "",
                base_url: str = "", settings: dict | None = None) -> dict:
    """Create a site row, or update the named fields of an existing one.

    Empty strings mean "leave alone" on update (create falls back:
    name → slug title, site_type → "custom"). Before this, an existing
    slug silently kept its old row — so the console Sites screen's edit
    (spec §5 "create/upsert rows") was a no-op.
    """
    init_db()
    s = get_session()
    try:
        site = _site_by_slug(s, slug)
        created = False
        updated = False
        if site is None:
            if not valid_site_slug(slug):
                return _err(f"invalid site slug {slug!r}",
                            "use lower-case letters, digits and hyphens (max 63 chars)")
            site = Site(slug=slug, name=name or slug.title(),
                        site_type=site_type or "custom", base_url=base_url,
                        settings=settings or {})
            s.add(site)
            s.commit()
            s.refresh(site)
            created = True
        else:
            if (name or "").strip():
                site.name = name
                updated = True
            if (site_type or "").strip():
                site.site_type = site_type
                updated = True
            if (base_url or "").strip():
                site.base_url = base_url
                updated = True
            if settings is not None:
                # Group-aware merge: a partial `wp` group no longer discards the
                # stored password; blank secret = keep, None = remove (plan CON-04).
                site.settings = merge_settings(site.settings, settings)
                updated = True
            if updated:
                s.commit()
                s.refresh(site)
        return {"id": site.id, "slug": site.slug, "created": created,
                "updated": updated}
    finally:
        s.close()


def delete_site(slug: str) -> dict:
    """Delete a site and cascade-clean its associated records if unreferenced."""
    init_db()
    s = get_session()
    try:
        site = _site_by_slug(s, slug)
        if site is None:
            return _err(f"site '{slug}' not found", "run list_sites for valid slugs")
        site_id = site.id
        # Delete dependent articles
        articles = s.execute(select(Article).where(Article.site_id == site_id)).scalars().all()
        for a in articles:
            s.execute(delete(CostLedger).where(CostLedger.article_id == a.id))
            s.execute(delete(BrainEntry).where(BrainEntry.article_id == a.id))
            s.execute(delete(ReviewFeedback).where(ReviewFeedback.article_id == a.id))
            s.execute(delete(AuditLog).where(AuditLog.article_id == a.id))
            s.delete(a)
        # Delete keywords
        s.execute(delete(KeywordLedger).where(KeywordLedger.site_id == site_id))
        s.execute(delete(BrainEntry).where(BrainEntry.site_id == site_id))
        s.execute(delete(ReviewFeedback).where(ReviewFeedback.site_id == site_id))
        s.execute(delete(AuditLog).where(AuditLog.site_id == site_id))
        # Every other table with a FK to sites.id. SQLite never enforced these, but
        # Postgres rejects the final DELETE with an FK violation (a 500) as soon as a
        # site has a brand profile -- which every provisioned site does (plan ENG-11).
        s.execute(delete(CostLedger).where(CostLedger.site_id == site_id))
        s.execute(delete(BrandProfile).where(BrandProfile.site_id == site_id))
        s.execute(delete(ShareOfVoice).where(ShareOfVoice.site_id == site_id))
        s.execute(delete(TavilyUsage).where(TavilyUsage.site_id == site_id))
        # A deleted site's API keys must stop working immediately (and FK-block the delete on Postgres).
        s.execute(delete(ApiKey).where(ApiKey.site_id == site_id))
        s.delete(site)
        # The site's own audit rows are gone, so leave one site-less record of the
        # deletion itself.
        s.add(AuditLog(site_id=None, action="site.deleted",
                       payload={"slug": slug, "id": site_id, "articles": len(articles)}))
        s.commit()
        return {"deleted": slug, "id": site_id}
    finally:
        s.close()


def delete_article(article_id: int) -> dict:
    """Delete an article while preserving spend and accounting records."""
    init_db()
    s = get_session()
    try:
        art = s.get(ArticleModel, article_id)
        if art is None:
            return _err(f"article {article_id} not found")
        site_id = art.site_id
        # Clean up related records
        s.execute(delete(CostLedger).where(CostLedger.article_id == article_id))
        s.execute(delete(BrainEntry).where(BrainEntry.article_id == article_id))
        s.execute(delete(ReviewFeedback).where(ReviewFeedback.article_id == article_id))
        s.execute(delete(AuditLog).where(AuditLog.article_id == article_id))
        s.delete(art)
        s.commit()
        return {"deleted": article_id}
    finally:
        s.close()


def delete_keyword(keyword_id: int) -> dict:
    """Delete a keyword ledger row."""
    init_db()
    s = get_session()
    try:
        kw = s.get(KeywordLedger, keyword_id)
        if kw is None:
            return _err(f"keyword {keyword_id} not found")
        # Unbind from articles first if any
        articles = s.execute(select(Article).where(Article.keyword_id == keyword_id)).scalars().all()
        for a in articles:
            a.keyword_id = None
        s.delete(kw)
        s.commit()
        return {"deleted": keyword_id}
    finally:
        s.close()


def prioritize_keyword(keyword_id: int, boost: float = 100.0) -> dict:
    """Prioritize a keyword by assigning it the highest priority score in the ledger."""
    init_db()
    s = get_session()
    try:
        kw = s.get(KeywordLedger, keyword_id)
        if kw is None:
            return _err(f"keyword {keyword_id} not found")
        # Find current maximum priority in the site's ledger
        max_prio = s.query(func.max(KeywordLedger.priority_score)).filter(KeywordLedger.site_id == kw.site_id).scalar() or 0.0
        kw.priority_score = max(max_prio + 10.0, boost)
        kw.status = "approved" if kw.status in ("queued", "researched") else kw.status
        s.commit()
        s.refresh(kw)
        return {
            "id": kw.id,
            "keyword": kw.keyword,
            "priority_score": kw.priority_score,
            "status": kw.status,
            "prioritized": True
        }
    finally:
        s.close()


def list_articles(site_slug: str = "", status: str = "", limit: int = 100,
                  offset: int = 0, q: str = "", sort: str = "created_at",
                  order: str = "desc", has_images: bool = False) -> dict:
    """List articles newest-first, optionally scoped to a site and/or status.

    Powers the custom-site **content loader** (§5.12 pull): enumerate a site's
    published articles, then fetch each one's `/content` payload by id. Only
    routing fields are returned (no html/markdown) — cheap to page through.

    Additive console filters (Wave 0+):
      - ``q`` matches title/slug (case-insensitive) in SQL so pagination
        counts stay correct.
      - ``sort``/``order`` control ordering: created_at|title|quality|cost|status
        (quality/cost are resolved in Python because they live in meta/ledger).
      - ``has_images`` restricts to rows with staged art (client Media page).
    All new params are optional and default to the legacy newest-first
    behavior, so existing callers (custom-site loader, MCP) are unaffected.
    """
    init_db()
    s = get_session()
    try:
        limit = max(1, min(int(limit or 100), 500))
        offset = max(0, int(offset or 0))
        stmt = select(Article)
        scoped_site = None
        if (site_slug or "").strip():
            scoped_site = _site_by_slug(s, site_slug.strip())
            if scoped_site is None:
                return _err(f"site '{site_slug}' not found",
                            "run list_sites for valid slugs")
            stmt = stmt.where(Article.site_id == scoped_site.id)
        if (status or "").strip():
            stmt = stmt.where(Article.status == status.strip())
        if (q or "").strip():
            # `%` / `_` / `\` in the search text are literals, not wildcards (ENG-17)
            esc = (q or "").strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            needle = f"%{esc}%"
            stmt = stmt.where(
                (Article.title.ilike(needle, escape="\\")) | (Article.slug.ilike(needle, escape="\\"))
            )
        if has_images:
            cand_rows = s.execute(
                stmt.with_only_columns(Article.id, Article.meta)
            ).all()
            img_ids = [r[0] for r in cand_rows
                       if isinstance(r[1], dict) and (r[1].get("images") or [])]
            if not img_ids:
                return {"articles": [], "count": 0, "total": 0,
                        "limit": limit, "offset": offset}
            stmt = stmt.where(Article.id.in_(img_ids))
        total = int(s.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
        sort_key = (sort or "created_at").strip().lower()
        order_desc = (order or "desc").strip().lower() != "asc"
        if sort_key in ("created_at", "title", "status"):
            col = {"created_at": Article.created_at, "title": Article.title,
                   "status": Article.status}[sort_key]
            order_expr = col.desc() if order_desc else col.asc()
            rows = s.execute(
                stmt.order_by(order_expr, Article.id.desc())
                    .limit(limit).offset(offset)
            ).scalars().all()
        elif sort_key == "cost":
            cost_sub = (select(func.coalesce(func.sum(CostLedger.amount_usd), 0.0))
                        .where(CostLedger.article_id == Article.id))
            rows = s.execute(
                stmt.order_by((cost_sub.scalar_subquery()).desc() if order_desc
                              else (cost_sub.scalar_subquery()).asc(),
                              Article.id.desc())
                    .limit(limit).offset(offset)
            ).scalars().all()
        elif sort_key == "quality":
            all_rows = s.execute(stmt).scalars().all()
            def _q(a):
                sc = (a.meta or {}).get("scores") if isinstance(a.meta, dict) else {}
                if not isinstance(sc, dict):
                    return 0.0
                v = sc.get("quality")
                if v is None:
                    v = sc.get("overall")
                if v is None:
                    sub = sc.get("sub_scores")
                    if isinstance(sub, dict):
                        v = sub.get("overall")
                try:
                    return float(v) if v is not None else 0.0
                except (TypeError, ValueError):
                    return 0.0
            all_rows.sort(key=_q, reverse=order_desc)
            rows = all_rows[offset:offset + limit]
        else:
            rows = s.execute(
                stmt.order_by(Article.created_at.desc(), Article.id.desc())
                    .limit(limit).offset(offset)
            ).scalars().all()
        slug_by_id: dict[int, str] = ({scoped_site.id: scoped_site.slug}
                                      if scoped_site else {})
        articles: list[dict] = []
        costs = _cost_map(s, [a.id for a in rows])
        for a in rows:
            if a.site_id not in slug_by_id:
                row = s.get(Site, a.site_id)
                slug_by_id[a.site_id] = row.slug if row else ""
            articles.append({
                "id": a.id, "site_id": a.site_id, "site_slug": slug_by_id[a.site_id],
                "title": a.title, "slug": _resolve_slug(a), "status": a.status,
                "created_at": _iso(a.created_at), "published_at": _iso(a.published_at),
                "cost_usd": costs.get(a.id, 0.0),
                # console Content screen (generated_posts sheet parity):
                # Quality Score + Summary columns, still no html/markdown.
                "quality": (
                    article_scores(a).get("quality")
                    or article_scores(a).get("overall")
                    or (article_scores(a).get("sub_scores", {}).get("overall")
                        if isinstance(article_scores(a).get("sub_scores"), dict) else None)
                ),
                "summary": (
                    (a.meta or {}).get("summary")
                    or (a.meta or {}).get("content_summary")
                    or (a.meta or {}).get("description")
                    or ""
                ),
                # console Media page: which articles have art, so it can
                # detail-fetch only those (still no image rows in the list).
                "images": len((a.meta or {}).get("images") or []),
                # real word count (replaces the console's "1,450 words" fallback)
                "word_count": len((a.content_md or "").split())
                if (a.content_md or "").strip() else 0,
            })
        return {"articles": articles, "count": len(articles), "total": total,
                "limit": limit, "offset": offset}
    finally:
        s.close()


def article_stats(site_slug: str = "", since_days: int = 30) -> dict:
    """Aggregated, real (engine-backed) stats for the operator console
    (Overview / Sites / Insights). Returns counts by status, quality
    aggregates, word totals, spend totals, and a per-day created/published
    series for the velocity chart. Additive — no change to list_articles
    behavior. `since_days` scopes the per-day series and the "recent" window;
    counts/quality are all-time.
    """
    init_db()
    s = get_session()
    try:
        since_days = max(1, int(since_days or 30))
        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
        stmt = select(Article)
        scoped_site = None
        if (site_slug or "").strip():
            scoped_site = _site_by_slug(s, site_slug.strip())
            if scoped_site is None:
                return _err(f"site '{site_slug}' not found",
                            "run list_sites for valid slugs")
            stmt = stmt.where(Article.site_id == scoped_site.id)
        rows = s.execute(stmt).scalars().all()
        slug_by_id: dict[int, str] = ({scoped_site.id: scoped_site.slug}
                                      if scoped_site else {})
        by_status: dict[str, int] = {}
        scored = 0
        qual_sum = 0.0
        qual_pass = 0  # >= 90 (engine publish gate threshold)
        words_total = 0
        in_range_created = 0
        in_range_published = 0
        per_day: dict[str, int] = {}
        per_site: dict[str, dict] = {}
        for a in rows:
            st = a.status or "unknown"
            by_status[st] = by_status.get(st, 0) + 1
            md = (a.content_md or "").strip()
            wc = len(md.split()) if md else 0
            words_total += wc
            sc = article_scores(a)
            q = sc.get("quality")
            if q is None:
                q = sc.get("overall")
            if q is None:
                sub = sc.get("sub_scores")
                if isinstance(sub, dict):
                    q = sub.get("overall")
            if q is not None:
                try:
                    qf = float(q)
                    scored += 1
                    qual_sum += qf
                    if qf >= 90:
                        qual_pass += 1
                except (TypeError, ValueError):
                    pass
            ca = a.created_at
            if ca is not None:
                if ca.tzinfo is None:
                    ca = ca.replace(tzinfo=timezone.utc)
                if ca >= cutoff:
                    in_range_created += 1
                dkey = ca.date().isoformat()
                per_day[dkey] = per_day.get(dkey, 0) + 1
                if a.status == "published":
                    pa = a.published_at or a.created_at
                    if pa is not None:
                        if pa.tzinfo is None:
                            pa = pa.replace(tzinfo=timezone.utc)
                        if pa >= cutoff:
                            in_range_published += 1
            if a.site_id not in slug_by_id:
                row = s.get(Site, a.site_id)
                slug_by_id[a.site_id] = row.slug if row else ""
            sl = slug_by_id[a.site_id]
            site_row = per_site.setdefault(sl, {
                "slug": sl, "articles": 0, "published": 0, "approved": 0,
                "quality_sum": 0.0, "scored": 0, "words": 0,
            })
            site_row["articles"] += 1
            site_row["words"] += wc
            if a.status == "published":
                site_row["published"] += 1
            if a.status == "approved":
                site_row["approved"] += 1
            if q is not None:
                try:
                    site_row["quality_sum"] += float(q)
                    site_row["scored"] += 1
                except (TypeError, ValueError):
                    pass
        for sl, sr in per_site.items():
            sr["quality_avg"] = round(sr["quality_sum"] / sr["scored"], 1) \
                if sr["scored"] else None
            del sr["quality_sum"]
        # cost ledger aggregates
        cost_base = select(func.coalesce(func.sum(CostLedger.amount_usd), 0.0)).where(
            CostLedger.kind != "total"
        )
        if scoped_site:
            ids_sub = select(Article.id).where(Article.site_id == scoped_site.id)
            cost_base = cost_base.where(
                (CostLedger.site_id == scoped_site.id)
                | (CostLedger.article_id.in_(ids_sub))
            )
        cost_total = float(s.scalar(cost_base) or 0.0)
        # per-kind split
        kind_rows = s.execute(
            select(CostLedger.kind, func.coalesce(func.sum(CostLedger.amount_usd), 0.0))
            .where(CostLedger.kind != "total")
            .group_by(CostLedger.kind)
        ).all()
        kind_totals = {k: float(v or 0.0) for k, v in kind_rows}
        if scoped_site:
            kind_rows = s.execute(
                select(CostLedger.kind, func.coalesce(func.sum(CostLedger.amount_usd), 0.0))
                .where(CostLedger.kind != "total")
                .where((CostLedger.site_id == scoped_site.id)
                       | (CostLedger.article_id.in_(ids_sub)))
                .group_by(CostLedger.kind)
            ).all()
            kind_totals = {k: float(v or 0.0) for k, v in kind_rows}
        # per-day series (sorted)
        series = [{"date": d, "created": per_day[d]} for d in sorted(per_day)]
        # keep only the last `since_days` entries
        series = series[-since_days:]
        return {
            "site_slug": (site_slug or "").strip(),
            "range_days": since_days,
            "total": len(rows),
            "by_status": by_status,
            "scored": scored,
            "avg_quality": round(qual_sum / scored, 1) if scored else None,
            "quality_pass_rate": round(100.0 * qual_pass / scored, 1) if scored else None,
            "words_total": words_total,
            "in_range": {"created": in_range_created,
                         "published": in_range_published},
            "cost": {"total_usd": round(cost_total, 4),
                     "per_kind": kind_totals,
                     "per_1k_words_usd": round(cost_total / (words_total / 1000.0), 4)
                     if words_total else None},
            "published_per_day": series,
            "sites": list(per_site.values()),
        }
    finally:
        s.close()


def list_queue(site_slug: str, status: str = "", limit: int = 100) -> dict:
    """Read-only keyword-ledger view for the operator console (parity §B1).

    Returns the ledger rows (newest first) plus per-status counts, so one
    call covers both the queue screen and the dashboard counters. Read-only:
    claiming stays an explicit action (get_brief / submit_article)."""
    init_db()
    limit = _clamp_limit(limit, 100)
    s = get_session()
    try:
        site = _site_by_slug(s, site_slug)
        if site is None:
            return _err(f"site '{site_slug}' not found", "run list_sites for valid slugs")
        counts: dict[str, int] = {}
        for st, n in s.execute(
            select(KeywordLedger.status, func.count())
            .where(KeywordLedger.site_id == site.id)
            .group_by(KeywordLedger.status)
        ):
            counts[st or ""] = n
        q = select(KeywordLedger).where(KeywordLedger.site_id == site.id)
        if (status or "").strip():
            q = q.where(KeywordLedger.status == status.strip())
        rows = s.execute(q.order_by(KeywordLedger.id.desc()).limit(limit)).scalars()
        queue = [
            {"id": r.id, "keyword": r.keyword, "status": r.status,
             "intent": r.intent, "volume": r.volume, "difficulty": r.difficulty,
             "priority_score": r.priority_score,
             "subject": (r.research_snapshot or {}).get("subject", ""),
             "added_at": _iso(r.added_at)}
            for r in rows
        ]
        return {"site": site.slug, "counts": counts, "queue": queue,
                "count": len(queue)}
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


def list_research(site_slug: str, status: str = "", limit: int = 100) -> dict:
    """Read-only research_data view for the console (Sheets parity).

    One row per keyword carrying the research worksheet's columns:
    subject, intent, volume, difficulty, content summary, primary/secondary
    keywords, and Generated (= a brief exists in the snapshot)."""
    init_db()
    limit = _clamp_limit(limit, 100)
    s = get_session()
    try:
        site = _site_by_slug(s, site_slug)
        if site is None:
            return _err(f"site '{site_slug}' not found", "run list_sites for valid slugs")
        q = select(KeywordLedger).where(KeywordLedger.site_id == site.id)
        if (status or "").strip():
            q = q.where(KeywordLedger.status == status.strip())
        rows = s.execute(q.order_by(KeywordLedger.id.desc()).limit(limit)).scalars()
        research = []
        for r in rows:
            snap = r.research_snapshot or {}
            research.append({
                "id": r.id, "keyword": r.keyword, "status": r.status,
                "intent": r.intent, "volume": r.volume, "difficulty": r.difficulty,
                "subject": snap.get("subject", ""),
                "summary": snap.get("summary", ""),
                "primary_keyword": snap.get("primary_keyword", ""),
                "secondary_keywords": snap.get("secondary_keywords", ""),
                "generated": bool(snap.get("brief")),
                "added_at": _iso(r.added_at),
            })
        return {"site": site.slug, "research": research, "count": len(research)}
    finally:
        s.close()


def list_briefs(site_slug: str, limit: int = 100) -> dict:
    """Read-only content_briefs view for the console (Sheets parity).

    Only rows whose research snapshot carries a brief (the content_briefs
    worksheet shape: brief content, FAQs, sources, summary, secondary
    keywords). Newest first; limit applies after the filter."""
    init_db()
    limit = _clamp_limit(limit, 100)
    s = get_session()
    try:
        site = _site_by_slug(s, site_slug)
        if site is None:
            return _err(f"site '{site_slug}' not found", "run list_sites for valid slugs")
        # Over-fetch: the brief lives in JSON, so the filter runs in Python.
        rows = s.execute(
            select(KeywordLedger).where(KeywordLedger.site_id == site.id)
            .order_by(KeywordLedger.id.desc()).limit(max(100, limit * 5))
        ).scalars()
        briefs = []
        for r in rows:
            snap = r.research_snapshot or {}
            if not snap.get("brief"):
                continue
            if len(briefs) >= limit:
                break
            briefs.append({
                "id": r.id, "keyword": r.keyword, "status": r.status,
                "intent": r.intent,
                "brief": snap.get("brief", ""),
                "faqs": snap.get("faqs", ""),
                "sources": snap.get("sources", ""),
                "summary": snap.get("summary", ""),
                "secondary_keywords": snap.get("secondary_keywords", ""),
            })
        return {"site": site.slug, "briefs": briefs, "count": len(briefs)}
    finally:
        s.close()


def _scope_site(s, site_slug: str, *, require_in_shared: bool = False):
    """Resolve an optional site filter -> (site | None, error | None).

    The old pattern was `site = lookup(slug) if slug else None` followed by "filter only if site is
    not None" -- so a MISTYPED slug, or no slug at all, silently returned every tenant's rows (plan
    ENG-08). Now:
      * a slug that doesn't exist is an error, never a wider query;
      * with `require_in_shared`, an empty slug on an engine that serves several sites
        (TENANCY_MODE=shared) is an error too -- tenant content must always be asked for by site;
      * an empty slug on a single-site engine still means "this instance's site(s)"."""
    from lib.site_env import is_shared_mode
    slug = (site_slug or "").strip()
    if slug:
        site = _site_by_slug(s, slug)
        if site is None:
            return None, _err(f"site '{slug}' not found", "run list_sites for valid slugs")
        return site, None
    if require_in_shared and is_shared_mode():
        return None, _err("site_slug is required: this engine serves several sites",
                          "pass the site's slug")
    return None, None


def _site_cost_filter(site_id: int):
    """CostLedger rows that belong to a site: recorded against it, or against one of its articles."""
    return (CostLedger.site_id == site_id) | (
        CostLedger.article_id.in_(select(Article.id).where(Article.site_id == site_id)))


def _month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def site_month_spend(s, site_id: int) -> float:
    """Month-to-date USD spent by one site (every cost row except the `total` roll-ups)."""
    q = (select(func.coalesce(func.sum(CostLedger.amount_usd), 0.0))
         .where(CostLedger.kind != "total", CostLedger.created_at >= _month_start())
         .where(_site_cost_filter(site_id)))
    return float(s.scalar(q) or 0.0)


def budget_status(s, site: Site) -> dict:
    """Spend vs the site's monthly cap (`Site.settings["budget"]["monthly_usd"]`; 0/unset = no cap)."""
    raw = ((site.settings or {}).get("budget") or {}).get("monthly_usd")
    try:
        cap = float(raw) if raw not in (None, "") else 0.0
    except (TypeError, ValueError):
        cap = 0.0
    spent = site_month_spend(s, site.id)
    return {"cap_usd": round(cap, 4) if cap > 0 else None, "mtd_usd": round(spent, 4),
            "remaining_usd": round(max(0.0, cap - spent), 4) if cap > 0 else None,
            "exceeded": bool(cap > 0 and spent >= cap)}


def _budget_block(s, art: ArticleModel) -> dict | None:
    """An error dict when this article's site has used up its monthly cap, else None. Called before
    every operation that spends money (LLM generation, image generation) so one client cannot run up
    the platform's bill (plan TEN-03). Publishing and reading are never blocked by it."""
    site = art.site
    if site is None:
        return None
    b = budget_status(s, site)
    if not b["exceeded"]:
        return None
    return {"error": (f"monthly spend cap reached for site '{site.slug}': ${b['mtd_usd']:.2f} of "
                      f"${b['cap_usd']:.2f} used this month"),
            "next": "raise settings.budget.monthly_usd for this site, or wait until next month",
            "code": "budget_exceeded", "budget": b}


def list_logs(kind: str = "", limit: int = 200, offset: int = 0, site_slug: str = "") -> dict:
    """Read-only logs view for the console (Sheets usage/audit parity).

    Returns audit rows (action-prefix filtered by `kind`: "usage" ->
    usage.model + usage.image rows, "publish" -> publish decisions; empty
    = all) plus the per-article cost ledger (llm|image|data|total).
    `offset` pages whichever list is surfaced — audit when `kind` selects
    one, the cost ledger when `kind` is "cost" or empty."""
    init_db()
    limit = _clamp_limit(limit, 200)
    s = get_session()
    try:
        site, bad = _scope_site(s, site_slug)
        if bad:
            return bad
        k = (kind or "").strip()
        offset = max(0, int(offset or 0))
        audit: list[dict] = []
        if k != "cost":
            aq = select(AuditLog)
            if site is not None:  # platform-wide rows (stage runs, usage) have no site and are excluded
                aq = aq.where(AuditLog.site_id == site.id)
            if k:
                aq = aq.where(AuditLog.action.startswith(k))
            audit_rows = s.execute(
                aq.order_by(AuditLog.id.desc()).limit(limit).offset(offset)
            ).scalars()
            audit = [{"id": a.id, "action": a.action, "article_id": a.article_id,
                      "payload": a.payload or {}, "created_at": _iso(a.created_at)}
                     for a in audit_rows]
        costs = []
        if not k or k == "cost":
            cq = select(CostLedger)
            if site is not None:
                cq = cq.where(_site_cost_filter(site.id))
            for c in s.execute(
                cq.order_by(CostLedger.id.desc())
                .limit(limit).offset(offset)
            ).scalars():
                costs.append({"id": c.id, "article_id": c.article_id, "kind": c.kind,
                              "amount_usd": c.amount_usd, "detail": c.detail or {},
                              "created_at": _iso(c.created_at)})
        return {"audit": audit, "costs": costs, "kind": k,
                "count": len(audit) + len(costs)}
    finally:
        s.close()


def get_spend_summary(site_slug: str = "") -> dict:
    """Aggregated spend summary computed entirely in SQL (§5.10-6).
    Returns WTD (week-to-date), MTD (month-to-date), and total spend."""
    init_db()
    s = get_session()
    try:
        now = datetime.now(timezone.utc)
        # Week start (Monday 00:00 UTC)
        day_of_week = now.weekday()
        wtd_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=day_of_week)
        # Month start (1st 00:00 UTC)
        mtd_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        site, bad = _scope_site(s, site_slug)
        if bad:
            return bad
        site_id = site.id if site is not None else None

        base_q = select(func.coalesce(func.sum(CostLedger.amount_usd), 0.0)).where(CostLedger.kind != "total")
        if site_id:
            # Match directly or through article
            article_ids = select(Article.id).where(Article.site_id == site_id)
            base_q = base_q.where(
                (CostLedger.site_id == site_id) | (CostLedger.article_id.in_(article_ids))
            )

        wtd_spend = float(s.scalar(base_q.where(CostLedger.created_at >= wtd_start)) or 0.0)
        mtd_spend = float(s.scalar(base_q.where(CostLedger.created_at >= mtd_start)) or 0.0)
        total_spend = float(s.scalar(base_q) or 0.0)

        return {
            "site_slug": site_slug,
            **({"budget": budget_status(s, site)} if site is not None else {}),
            "wtd_usd": round(wtd_spend, 4),
            "mtd_usd": round(mtd_spend, 4),
            "total_usd": round(total_spend, 4),
            "wtd_formatted": f"${wtd_spend:.2f}" if wtd_spend >= 1 else f"${wtd_spend:.4f}",
            "mtd_formatted": f"${mtd_spend:.2f}" if mtd_spend >= 1 else f"${mtd_spend:.4f}",
            "total_formatted": f"${total_spend:.2f}" if total_spend >= 1 else f"${total_spend:.4f}",
        }
    finally:
        s.close()


def record_stage_run(stage: str, *, ok: bool, detail: str = "",
                     duration_ms: int = 0,
                     started_at: datetime | None = None) -> None:
    """One `stage.run` audit row per finished stage run (console Wave 5).

    Written by the run route's background task — telemetry only: the caller
    treats a recording failure as non-fatal (it must never mask the stage
    outcome), and scheduled CI runs (`scripts/run_stage.py` on Actions)
    write this in their own environment, not here."""
    init_db()
    s = get_session()
    try:
        s.add(AuditLog(action="stage.run", payload={
            "stage": stage,
            "ok": bool(ok),
            "detail": str(detail or "")[:400],
            "duration_ms": max(0, int(duration_ms or 0)),
            "started_at": _iso(started_at) or "",
        }))
        s.commit()
    finally:
        s.close()


def list_stages(running: list[str] | None = None, limit: int = 200) -> dict:
    """Read-only stages view for the console (Wave 5).

    Newest `stage.run` audit rows first (completed runs only — one row per
    finished run), a per-stage last-run rollup, and the caller-supplied live
    running set (process-local: whatever this engine instance has in
    flight right now)."""
    init_db()
    s = get_session()
    try:
        limit = max(1, min(int(limit or 200), 500))
        rows = s.execute(
            select(AuditLog).where(AuditLog.action == "stage.run")
            .order_by(AuditLog.id.desc()).limit(limit)
        ).scalars()
        history = []
        for r in rows:
            p = r.payload or {}
            history.append({
                "id": r.id,
                "stage": str(p.get("stage", "")),
                "ok": bool(p.get("ok", False)),
                "detail": str(p.get("detail", "")),
                "duration_ms": int(p.get("duration_ms") or 0),
                "started_at": str(p.get("started_at", "")),
                "finished_at": _iso(r.created_at),
            })
        last: dict[str, dict] = {}
        for h in history:
            last.setdefault(h["stage"], h)
        return {"running": sorted(running or []), "last": last,
                "history": history, "count": len(history)}
    finally:
        s.close()


async def run_instant_pipeline(article_id: int) -> dict:
    """End-to-end instant runner: generates content -> stages images in background."""
    try:
        gen_res = await generate_content(article_id)
        if "error" in gen_res:
            logger.warning(f"run_instant_pipeline generate error on #{article_id}: {gen_res}")
            return gen_res
        try:
            stage_images(article_id)
        except Exception as e:
            logger.warning(f"run_instant_pipeline image staging exception on #{article_id}: {e}")
        return {"id": article_id, "status": "drafted", "instant_ready": True}
    except Exception as e:
        logger.exception(f"run_instant_pipeline failed on #{article_id}: {e}")
        return {"id": article_id, "error": str(e)}


_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62})$")


def valid_site_slug(slug: str) -> bool:
    """Lower-case letters, digits and hyphens, 1-63 chars, not starting with a hyphen. The slug is used in
    URLs, file names and cache keys, so anything else (spaces, slashes, unicode tricks) is refused (ENG-13)."""
    return bool(_SLUG_RE.match(slug or ""))


def _may_autocreate_site(slug: str) -> bool:
    """Submitting an article may create its site only for the instance's own default site, or when the
    operator opted in with SDK_AUTO_CREATE_SITES=1. Otherwise a typo ('blgo' for 'blog') silently created a
    phantom tenant and the article vanished from the real one."""
    from lib.store import DEFAULT_SITE_SLUG
    if (os.environ.get("SDK_AUTO_CREATE_SITES") or "").strip().lower() in ("1", "true", "yes", "on"):
        return True
    return slug == DEFAULT_SITE_SLUG


def submit_article(site_slug: str, keyword: str = "", brief: dict | None = None,
                   create_site: bool = True) -> dict:
    """Create an article in 'briefed' state. Idempotent per (site, keyword).

    §5.16 lineage: when a keyword is given, the article is bound to its ledger
    row (resolved or created), so "zero articles without a keyword row" holds
    for anything submitted through the SDK/MCP.

    `create_site=False` (what the REST and MCP entry points pass unless `_may_autocreate_site`) makes an
    unknown slug an error instead of inventing a tenant. Internal callers keep the old behaviour."""
    init_db()
    s = get_session()
    try:
        site = _site_by_slug(s, site_slug)
        if site is None:
            if not valid_site_slug(site_slug):
                return _err(f"invalid site slug {site_slug!r}",
                            "use lower-case letters, digits and hyphens (max 63 chars)")
            if not create_site:
                return _err(f"site '{site_slug}' not found",
                            "create it first (upsert_site / console Sites), or check the spelling; "
                            "set SDK_AUTO_CREATE_SITES=1 to restore create-on-submit")
            site = Site(slug=site_slug, name=site_slug.title())
            s.add(site)
            s.commit()
            s.refresh(site)
        title = (brief or {}).get("title") or keyword or "Untitled"
        # Dedupe prefers the keyword binding: generation renames the article
        # title to the generated H1, so a title-only lookup would miss the
        # existing row and create a duplicate on a repeat submit.
        keyword_id = None
        existing = None
        if (keyword or "").strip():
            kw_row = upsert_keyword(s, site.id, keyword.strip())
            keyword_id = kw_row.id
            existing = s.execute(
                select(ArticleModel).where(ArticleModel.site_id == site.id,
                                           ArticleModel.keyword_id == keyword_id)
            ).scalars().first()
        if existing is None:
            existing = s.execute(
                select(ArticleModel).where(ArticleModel.site_id == site.id,
                                           ArticleModel.title == title)
            ).scalars().first()
        if existing is not None:
            return {"id": existing.id, "status": existing.status, "deduplicated": True,
                    "event": "article.ready"}
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


def _focus_keyphrase(meta: dict, brief: dict) -> str:
    """Focus keyphrase for the SEO meta (Yoast/Rank Math): the submitted
    keyword first (what the page was written for), then the brief's."""
    for src in (brief, meta):
        val = str((src or {}).get("keyword") or "").strip()
        if val:
            return val
    return ""


def _content_sections(md: str) -> list[dict]:
    """`## ` sections of a draft: {index, heading, text}.

    `index` counts ALL H2 headings (1-based) so it lines up with
    wp_render.inject_inpost_images' heading-block anchors; trailing
    Sources/FAQ sections are excluded as image targets."""
    text = md or ""
    heads = list(re.finditer(r"^##[ \t]+(.+)$", text, re.M))
    out: list[dict] = []
    for pos, m in enumerate(heads):
        heading = m.group(1).strip()
        if re.match(r"(sources|frequently asked questions|faqs?)\b",
                    heading, re.I):
            continue
        end = heads[pos + 1].start() if pos + 1 < len(heads) else len(text)
        out.append({"index": pos + 1, "heading": heading,
                    "text": text[m.end():end].strip()})
    return out


def _clamp_limit(limit: Any, default: int = 100, hi: int = 500) -> int:
    """A usable page size. An unclamped `limit` was a footgun: a negative value means "no limit" on
    SQLite and a 500 on Postgres, and a huge one loads the whole table (plan ENG-17)."""
    try:
        n = int(limit)
    except (TypeError, ValueError):
        n = default
    return max(1, min(n, hi))


def _stale_year_re(now: datetime | None = None) -> "re.Pattern[str]":
    """Matches 'in <past year>' (2010 .. last year). The pattern used to be hard-coded to
    20(1\\d|2[0-5]), so from 2026 on it never flagged a stale 'in 2025'/'in 2026' again."""
    current = (now or datetime.now(timezone.utc)).year
    return re.compile(rf"\bin\s+(?:{'|'.join(str(y) for y in range(2010, current))})\b", re.I)


def _content_checks(*, content: str, title: str, summary: str,
                    faqs: list | None, brief: dict) -> dict:
    """Deterministic draft gate — every check is {pass, value, need}.

    Checks whose inputs are absent (no link candidates, no sources) pass
    fail-open so a sparse brief never dead-locks generation; only provable
    failures report. The word floor is intent-aware (`word_floor_for` —
    compact buyer-intent pages floor at their template's 400-500, flagship
    informational at 900) with `GEN_MIN_WORDS` as an operator override."""
    from lib.brief_templates import faq_min_for, word_floor_for
    from lib.seo_keywords import check_keywords, parse_keywords

    words = len((content or "").split())
    min_words = word_floor_for(
        str(brief.get("template_intent") or brief.get("intent") or ""),
        str(brief.get("keyword") or brief.get("primary_keyword") or ""))
    md_links = re.findall(r"\[[^\]]*\]\(([^)\s]+)\)", content or "")
    site_base = str(brief.get("site_base_url") or "").rstrip("/")
    internal = [l for l in md_links if site_base and l.startswith(site_base)]
    external = [l for l in md_links
                if l.startswith(("http://", "https://"))
                and not (site_base and l.startswith(site_base))]
    stale_re = _stale_year_re()
    checks: dict[str, dict] = {
        "words": {"pass": words >= min_words, "value": words, "need": min_words},
        "tldr": {"pass": bool(re.search(r"TL\s*;?\s*DR", (content or "")[:800], re.I))},
        "sources": {"pass": bool(re.search(r"^##[ \t]+Sources\b", content or "", re.M | re.I))},
        "faqs": {"pass": len(faqs or []) >= faq_min_for(brief), "value": len(faqs or []),
                 "need": faq_min_for(brief)},
        "stale_year": {"pass": not stale_re.search(title or "")
                       and not stale_re.search(content or "")},
        "summary": {"pass": 0 < len((summary or "").strip()) <= 160,
                    "value": len((summary or "").strip()), "need": 160},
    }
    candidates = brief.get("internal_links") or []
    if candidates:
        need = min(3, len(candidates))
        checks["internal_links"] = {"pass": len(internal) >= need,
                                    "value": len(internal), "need": need}
    if brief.get("sources"):
        checks["external_links"] = {"pass": len(external) >= 1,
                                    "value": len(external), "need": 1}
    # Operator-supplied SECONDARY keyword targets -- hard-gated. The primary
    # keyword is NOT gated here: it is the ledger topic and the prompts
    # already enforce it (H1, TL;DR, intro), so counting it would reject
    # drafts that legitimately use it once. Only the secondary targets are
    # new data with no other enforcement point.
    # Fail-open when the operator supplied none -- that is how the 2026-10-08
    # featured-image incident deadlocked a post, and it must not repeat here.
    kw = check_keywords(content, primary="", secondary=parse_keywords(
        str(brief.get("secondary_keywords") or ""))[0])
    if kw["checked"]:
        checks["keyword_usage"] = {
            "pass": kw["pass"],
            "value": [c["total"] for c in kw["counts"]],
            "need": [c["min_uses"] for c in kw["counts"]],
            "counts": kw["counts"],
            "missing": kw["missing"],
            "guidance": kw["guidance"],
        }
    return checks


def _checks_pass(checks: dict) -> bool:
    return all(bool(c.get("pass")) for c in (checks or {}).values())


def _merge_usage(base: dict, add: dict) -> dict:
    """Sum token usage across revise-loop attempts (models deduped)."""
    if not add:
        return base
    if not base:
        return dict(add)
    out = dict(base)
    for k in ("requests", "input_tokens", "output_tokens", "total_tokens"):
        out[k] = int(out.get(k) or 0) + int(add.get(k) or 0)
    models = list(out.get("models") or [])
    for m in (add.get("models") or []):
        if m not in models:
            models.append(m)
    if models:
        out["models"] = models
    return out


def _wp_config(site=None):
    """WordPress credentials for one site.

    Site.settings["wp"] = {"base_url", "username", "app_password"} wins;
    otherwise the process WP_* env (one WP per instance). Per-site
    resolution means a shared engine can never push site B's article into
    site A's WordPress — the highest-severity cross-instance bleed there
    is. Post-id-scoped ops (wp_post/_elementor_client) have no article to
    resolve from and stay env-based.

    Shared mode (TENANCY_MODE=shared, one process / many sites): there is no
    "the" WordPress for the process, so a site without its own settings["wp"]
    gets an EMPTY config (callers report "not configured") instead of silently
    publishing into whichever WP the process env names -- or, in site_health,
    sending that site's password to another tenant's host (plan TEN-01 / SEC-08)."""
    from lib.site_env import is_shared_mode
    from lib.wordpress import WPConfig

    settings = getattr(site, "settings", None)
    wp = settings.get("wp") if isinstance(settings, dict) else None
    if isinstance(wp, dict) and wp.get("base_url"):
        return WPConfig(base_url=str(wp.get("base_url") or "").rstrip("/"),
                        username=str(wp.get("username") or ""),
                        app_password=str(wp.get("app_password") or ""))
    if is_shared_mode():
        return WPConfig(base_url="", username="", app_password="")
    return WPConfig.from_env()


def test_wp_connection(site_slug: str, wp_config: dict | None = None) -> dict:
    """Test WordPress REST API connection and authentication.

    If wp_config is provided ({base_url, username, app_password}), tests that config.
    Otherwise uses the site's configured settings or environment fallback.
    """
    init_db()
    s = get_session()
    try:
        site = _site_by_slug(s, site_slug)
        if site is None:
            return _err(f"site '{site_slug}' not found", "run list_sites for valid slugs")

        import requests
        from lib.wordpress import WPConfig

        if wp_config and isinstance(wp_config, dict) and wp_config.get("base_url"):
            cfg = WPConfig(
                base_url=str(wp_config.get("base_url") or "").rstrip("/"),
                username=str(wp_config.get("username") or "").strip(),
                app_password=str(wp_config.get("app_password") or "").strip(),
            )
        else:
            cfg = _wp_config(site)

        if not cfg.base_url:
            return {"ok": False, "error": "No WordPress base URL configured"}
        if not cfg.username or not cfg.app_password:
            return {"ok": False, "error": "Missing WordPress username or application password"}

        url = f"{cfg.base_url}/wp-json/wp/v2/users/me"
        try:
            r = safe_get(url, headers=cfg.auth_header(), timeout=8, max_bytes=1024 * 1024)
            if r.status_code == 200:
                data = r.json() or {}
                return {
                    "ok": True,
                    "user_id": data.get("id"),
                    "username": data.get("slug") or data.get("name") or cfg.username,
                    "roles": data.get("roles", []),
                    "base_url": cfg.base_url,
                    "message": f"Successfully authenticated as {data.get('name', cfg.username)} ({', '.join(data.get('roles', []))})"
                }
            elif r.status_code in (401, 403):
                return {
                    "ok": False,
                    "status_code": r.status_code,
                    "error": f"Authentication failed (HTTP {r.status_code}). Please verify username and application password."
                }
            else:
                return {
                    "ok": False,
                    "status_code": r.status_code,
                    "error": f"WordPress REST API returned HTTP {r.status_code} at {url}."
                }
        except Exception as e:
            return {"ok": False, "error": f"Connection error: {str(e)}"}
    finally:
        s.close()



def _enrich_brief_with_links(art: ArticleModel, brief: dict, keyword: str) -> dict:
    """Embed REAL internal-link candidates into the generation brief.

    The generator's own link tools only know the Sanity site; WordPress
    articles need candidates from the target WP itself. Production-only
    (site_type=wordpress + WP_* env) — CI/tests never satisfy both, so no
    network in tests. Fail-open: any problem means the brief stays as-is."""
    if (getattr(art.site, "site_type", "") or "") != "wordpress":
        return brief
    try:
        from lib.wordpress import WordPressConnector

        cfg = _wp_config(art.site)
        if not (cfg.base_url and cfg.username and cfg.app_password):
            return brief
        conn = WordPressConnector(cfg)
        own = _resolve_slug(art)
        picked: list[dict] = []
        seen: set[str] = {own}

        def _add(links: list[dict]) -> None:
            for l in links or []:
                slug = str(l.get("slug") or "").rstrip("/")
                url = str(l.get("url") or "")
                if not url or (slug and slug in seen):
                    continue
                if slug:
                    seen.add(slug)
                picked.append({"title": str(l.get("title") or "").strip(),
                               "url": url})
                if len(picked) >= 6:
                    return

        _add(conn.fetch_internal_links(keyword or art.title or "", per_page=10))
        if len(picked) < 3:
            _add(conn.list_posts(per_page=10))
        if not picked:
            return brief
        out = dict(brief)
        out["internal_links"] = picked
        out["site_base_url"] = cfg.base_url.rstrip("/")
        return out
    except Exception:
        return brief


def _stage_copy(src: str, art_id: int, slot: str, n: int = 0) -> str | None:
    """Copy a generated image to a stable staging path so the file survives
    past the NamedTemporaryFile that produced it (publish/refresh re-upload
    from meta.images later)."""
    try:
        d = os.environ.get("IMAGE_STAGING_DIR") or os.path.join(
            tempfile.gettempdir(), "contentfte_images")
        os.makedirs(d, exist_ok=True)
        ext = os.path.splitext(src)[1] or ".jpg"
        suffix = f"_{n}" if n else ""
        dst = os.path.join(d, f"article{art_id}_{slot}{suffix}{ext}")
        shutil.copyfile(src, dst)
        return dst
    except Exception:
        return None


def _stage_images_for(art: ArticleModel, meta: dict, *,
                      reason: str = "manual") -> dict:
    """Generate + stage featured/in-post images into meta.images (§5.9).

    Stock-first in-section in-post via _select_inpost_image; featured is
    AI-only. Section-aware: each in-post image is generated for one `## `
    section (its own prompt headline + summary, never the whole-article
    title) with `after_h2` set so publish injects it INLINE, before the
    FAQ. Skips cleanly with no provider credentials (CI/tests: zero
    network). Never raises — returns what happened."""
    if isinstance(meta.get("images"), list) and meta["images"]:
        return {"skipped": "images already staged", "reason": reason}
    if not (os.environ.get("CLOUDFLARE_API_TOKEN")
            or os.environ.get("PEXELS_API_KEY")):
        return {"skipped": "no image provider credentials "
                           "(CLOUDFLARE_API_TOKEN / PEXELS_API_KEY)",
                "reason": reason}
    try:
        from tools.tools import _generate_image, _select_inpost_image
    except Exception as exc:  # noqa: BLE001 — fail-open contract
        return {"error": f"image tools unavailable: {exc}", "reason": reason}

    keyword = str(meta.get("keyword") or art.title or "").strip()
    title = str(art.title or "")
    summary = str(meta.get("summary") or "")
    rows: list[dict] = []
    out: dict[str, Any] = {"reason": reason, "featured": False,
                           "inpost": 0, "errors": []}

    try:
        res = _generate_image(keyword=keyword, title=title,
                              summary=summary, slot="featured")
    except Exception as exc:  # noqa: BLE001
        res = {"error": str(exc)}
    if isinstance(res, dict) and res.get("image_url"):
        staged = _stage_copy(str(res["image_url"]), art.id, "featured") \
            or str(res["image_url"])
        alt = (summary or keyword or title)[:125].strip()
        row: dict[str, Any] = {"slot": "featured", "path": staged, "alt": alt}
        if res.get("source"):
            row["source"] = str(res["source"])[:120]
        if isinstance(res.get("cost_usd"), (int, float)):
            row["cost_usd"] = float(res["cost_usd"])
        if isinstance(res.get("qa"), dict):
            # Jev style pick + VLM lanes — the Wave-3 Media tab reads these.
            row["qa"] = res["qa"]
        rows.append(row)
        out["featured"] = True
    elif isinstance(res, dict) and (res.get("error") or res.get("skipped")):
        out["errors"].append(f"featured: {res.get('error') or res.get('skipped')}")

    sections = [s for s in _content_sections(art.content_md or "")
                if s["heading"]]
    words = len((art.content_md or "").split())
    want = 2 if words >= 1300 else 1
    pool = sections[1:] or sections
    picks: list[dict] = []
    if pool:
        picks = [pool[0]]
        if want == 2 and len(pool) > 1:
            picks.append(pool[-1])
    for i, sec in enumerate(picks):
        alt_ip = f"{keyword}: {sec['heading']}"[:125] if keyword \
            else sec["heading"][:125]
        try:
            r2 = _select_inpost_image(
                topic=sec["heading"] or keyword,
                section_summary=(sec["text"] or summary)[:600],
                alt_text=alt_ip)
        except Exception as exc:  # noqa: BLE001
            r2 = {"error": str(exc)}
        src = ""
        if isinstance(r2, dict):
            src = str(r2.get("image_url") or r2.get("url") or "")
        if src:
            local = os.path.isfile(src)
            staged = _stage_copy(src, art.id, "inpost", i) if local else None
            row = {"slot": "inpost", ("path" if (staged or local) else "url"):
                   staged or src, "alt": alt_ip, "after_h2": sec["index"]}
            if isinstance(r2.get("cost_usd"), (int, float)):
                row["cost_usd"] = float(r2["cost_usd"])
            if isinstance(r2.get("qa"), dict):
                # Jev style pick + VLM lanes — the Wave-3 Media tab reads these.
                row["qa"] = r2["qa"]
            rows.append(row)
            out["inpost"] += 1
        else:
            err = (r2 or {}).get("error") if isinstance(r2, dict) else "failed"
            out["errors"].append(
                f"inpost[{sec['heading'][:40]}]: {err or 'no image'}")
    if rows:
        meta["images"] = rows
    return out


def stage_images(article_id: int) -> dict:
    """Public op: stage images into meta.images when missing (§5.9).

    Wired REST `POST /sdk/v1/articles/{id}/stage-images` + MCP
    `contentfte_stage_images`. publish_article calls the same helper
    automatically, so this is for pre-approval visibility / retries."""
    init_db()
    s = get_session()
    try:
        art = s.get(ArticleModel, article_id)
        if art is None:
            return _err(f"article {article_id} not found",
                        "submit one first: contentfte_submit_article")
        blocked = _budget_block(s, art)
        if blocked:
            return blocked
        meta = dict(art.meta) if isinstance(art.meta, dict) else {}
        out = _stage_images_for(art, meta, reason="manual")
        if meta.get("images"):
            # Mirror publish: record what this call did on the article. The
            # skip paths never set `featured`, so an idempotent re-call won't
            # clobber publish-time metadata.
            if out.get("featured") is not None:
                meta["image_staging"] = {k: out.get(k)
                                         for k in ("reason", "featured",
                                                   "inpost", "errors", "skipped")
                                         if out.get(k) is not None}
            img_usd = 0.0
            if not meta.get("image_costs_recorded"):
                img_usd = sum(float(r.get("cost_usd") or 0.0)
                              for r in (meta.get("images") or [])
                              if isinstance(r, dict))
                meta["image_costs_recorded"] = True
            # Single assignment AFTER every mutation: record_cost below
            # commits this flush together with its ledger row. Mutating
            # `meta` in place after an earlier commit is invisible to
            # SQLAlchemy (the in-memory committed object mutates too, so
            # history shows no net change and the UPDATE never fires).
            art.meta = dict(meta)
            if img_usd > 0:
                try:
                    record_cost(s, art.id, "image", round(img_usd, 6),
                                detail={"slots": len(meta["images"]),
                                        "reason": "manual staging"})
                except Exception:
                    pass
            s.add(AuditLog(article_id=art.id, site_id=art.site_id,
                           action="article.images",
                           payload={"event": "article.images_staged",
                                    **{k: out.get(k)
                                       for k in ("featured", "inpost",
                                                 "skipped", "errors")}}))
            s.commit()
        return {"id": art.id, "event": "article.images",
                "images": len(meta.get("images") or []), **out}
    finally:
        s.close()


def _find_image_row(meta_images: list, asked_name: str) -> dict | None:
    """The meta.images row whose ``path`` basename is *asked_name*.

    Mirrors the allowlist logic in ``get_article_image`` so the regenerate op
    can only ever target images the article actually references; remote-only
    rows (``url``, no local ``path``) are not regeneratable by name."""
    if not isinstance(meta_images, list):
        return None
    for row in meta_images:
        if not isinstance(row, dict):
            continue
        p = str(row.get("path") or "")
        if p and os.path.basename(p) == asked_name:
            return row
    return None


def regenerate_article_image(article_id: int, image_name: str) -> dict:
    """Re-generate one staged meta.images row (featured or inpost).

    - Only allowlisted by the article's own ``meta.images`` rows (path basename
      must match *image_name*).
    - Featured rows: re-run ``_generate_image`` with the same keyword/title/summary,
      copy to staging, replace the row in-place (keep slot/after_h2/alt).
    - Inpost rows: re-run ``_select_inpost_image`` using the section that the
      row's ``after_h2`` points to (heading + trimmed text as prompt), replace
      the row in-place (keep slot/after_h2/alt).
    - ``cost_usd`` and ``qa`` are overwritten from the new generation.
    - Best-effort: if no provider credentials, return ``skipped``; any error
      returns ``{"error": "...}`` but does NOT raise — the caller should surface
      the user a confirm dialog (spends credits) and a cost surface.
    - Never raises — returns what happened, just like ``_stage_images_for``.
    """
    init_db()
    s = get_session()
    try:
        art = s.get(ArticleModel, article_id)
        if art is None:
            return _err(f"article {article_id} not found", "run list_articles first")
        blocked = _budget_block(s, art)
        if blocked:
            return blocked
        # Deep copy before mutating: a shallow copy shares the nested `images`
        # row objects with the committed value, so an in-place row edit would
        # compare EQUAL to the old meta and SQLAlchemy would never mark the
        # column dirty (no UPDATE fires — see the stage_images note).
        meta = copy.deepcopy(art.meta) if isinstance(art.meta, dict) else {}
        rows = meta.get("images") if isinstance(meta.get("images"), list) else []
        row = _find_image_row(rows, str(image_name or "").strip())
        if row is None:
            return _err(f"image '{image_name}' not found on article {article_id}",
                        "the article's meta.images rows are the allowlist")
        if not (os.environ.get("CLOUDFLARE_API_TOKEN")
                or os.environ.get("PEXELS_API_KEY")):
            return {"skipped": "no image provider credentials "
                               "(CLOUDFLARE_API_TOKEN / PEXELS_API_KEY)",
                    "reason": "regenerate", "featured": False, "inpost": 0,
                    "images": len(rows), "errors": []}
        slot = "inpost" if row.get("slot") == "inpost" else "featured"
        after_h2 = int(row.get("after_h2") or 0)
        keyword = str(meta.get("keyword") or art.title or "").strip()
        title = str(art.title or "")
        summary = str(meta.get("summary") or "")
        try:
            from tools.tools import _generate_image, _select_inpost_image
        except Exception as exc:  # noqa: BLE001 — fail-open contract
            return {"error": f"image tools unavailable: {exc}",
                    "reason": "regenerate", "featured": False, "inpost": 0,
                    "images": len(rows), "errors": []}

        ok = False
        err = ""
        res: dict[str, Any] = {}
        if slot == "featured":
            try:
                res = _generate_image(keyword=keyword, title=title,
                                      summary=summary, slot="featured")
            except Exception as exc:  # noqa: BLE001
                res = {"error": str(exc)}
            res = res if isinstance(res, dict) else {}
            if res.get("image_url"):
                # Same staged name as stage-images: the file is replaced in
                # place, keeping slot/after_h2 and the row's position.
                row.pop("url", None)
                row["path"] = _stage_copy(str(res["image_url"]), art.id,
                                          "featured") or str(res["image_url"])
                ok = True
            else:
                err = str(res.get("error") or res.get("skipped") or "no image")
        else:  # slot == "inpost"
            # Reuse the section the row's after_h2 points at (1-based over all
            # H2s) — the same anchor publish injects before.
            sections = [sec for sec in _content_sections(art.content_md or "")
                        if sec["heading"]]
            target = next((sec for sec in sections if sec["index"] == after_h2),
                          None) or (sections[0] if sections else {})
            topic = str(target.get("heading") or keyword)
            try:
                res = _select_inpost_image(
                    topic=topic,
                    section_summary=str(target.get("text") or summary)[:600],
                    alt_text=str(row.get("alt") or topic)[:125])
            except Exception as exc:  # noqa: BLE001
                res = {"error": str(exc)}
            res = res if isinstance(res, dict) else {}
            src = str(res.get("image_url") or res.get("url") or "")
            if src:
                if os.path.isfile(src):  # freshly generated local file
                    row.pop("url", None)
                    row["path"] = _stage_copy(src, art.id, "inpost") or src
                else:  # remote stock: keep the URL, never a fake path
                    row.pop("path", None)
                    row["url"] = src
                ok = True
            else:
                err = str(res.get("error") or "no image")

        new_cost = 0.0
        if ok:
            # Cost and QA are overwritten from the new result (old scores are
            # stale the moment the file changed).
            if isinstance(res.get("cost_usd"), (int, float)):
                new_cost = float(res["cost_usd"])
            if slot == "featured":
                row["alt"] = (summary or keyword or title)[:125].strip()
            row["cost_usd"] = new_cost
            row["qa"] = res["qa"] if isinstance(res.get("qa"), dict) else {}
            if res.get("source"):
                row["source"] = str(res["source"])[:120]
            meta["images"] = rows
            art.meta = meta  # single assignment, beside the audit row below
            if new_cost > 0:
                # A regenerate is a new spend: ledger it (the staged rows were
                # already counted once via image_costs_recorded).
                try:
                    record_cost(s, art.id, "image", round(new_cost, 6),
                                detail={"slot": slot, "reason": "regenerate"})
                except Exception:
                    pass
            via = f" (after_h2={after_h2})" if slot == "inpost" else ""
            detail = f"{slot} image '{image_name}'{via} regenerated"
            if new_cost:
                detail += f", cost=${new_cost:.4f}"
        else:
            detail = f"{slot} image '{image_name}' regenerate failed: {err}"
        s.add(AuditLog(article_id=art.id, site_id=art.site_id,
                       action="article.images",
                       payload={"event": "article.images_regenerated",
                                "slot": slot, "image": image_name,
                                "ok": ok, "detail": detail[:400]}))
        s.commit()
        return {"id": art.id, "event": "article.images",
                "images": len(meta.get("images") or []),
                "reason": "regenerate",
                "featured": slot == "featured" and ok,
                "inpost": 1 if (slot == "inpost" and ok) else 0,
                "errors": [] if ok else [err],
                "detail": detail}
    finally:
        s.close()


async def _default_generate(brief: dict) -> str:
    """Production generation seam: lazily runs content_generator_agent
    (heavy agents stack loads only on first generation). Tests and the MCP
    end-to-end smoke monkeypatch this — never hit the network in CI."""
    from blog_agent.generation import generate_with_agent

    return await generate_with_agent(brief)


async def generate_content(article_id: int, *, generate_fn=None,
                           regenerate: bool = False) -> dict:
    """One generation per article at a time (a concurrent call returns `code: generation_in_progress`
    instead of paying for a second LLM run that would overwrite the first). See `_generate_content_locked`."""
    if not _claim("generate", article_id):
        return {"error": f"article {article_id} is already being generated",
                "next": "wait for the current generation to finish, then check the article",
                "code": "generation_in_progress"}
    try:
        return await _generate_content_locked(article_id, generate_fn=generate_fn, regenerate=regenerate)
    finally:
        _release("generate", article_id)


async def _generate_content_locked(article_id: int, *, generate_fn=None,
                                   regenerate: bool = False) -> dict:
    """§5.5/§5.13 — real generation behind generate_article: briefed → drafted.

    Composes the brief in-memory (submitted brief + ledger research + intent
    template), runs `generate_fn` (default: the shared content_generator_agent
    with the article's brief embedded — no Sheets involved), then persists the
    envelope onto the Article (content_md, title, summary, FAQs, quality
    score), advances the ledger row to 'drafted', and writes an audit row.

    Idempotent: an article that already has content returns as-is (pass
    regenerate=true to rewrite; an approved article reverts to 'drafted' so
    it must be re-approved before publishing). Fail-open: every failure —
    runner exception, unusable output, envelope status=error — comes back
    as {"error", "next"}, never raises, and leaves the row untouched.
    """
    init_db()
    s = get_session()
    try:
        art = s.get(ArticleModel, article_id)
        if art is None:
            return _err(f"article {article_id} not found",
                        "submit one first: contentfte_generate_article / POST /sdk/v1/articles")
        if (art.content_md or "").strip() and not regenerate:
            return {"id": art.id, "status": art.status, "event": "article.drafted",
                    "deduplicated": True, "has_content": True}
        if art.status == "published" and not regenerate:
            return _err(f"article {article_id} is published",
                        "pass regenerate=true to rewrite it (status returns to 'drafted')")
        blocked = _budget_block(s, art)
        if blocked:
            return blocked

        meta = art.meta if isinstance(art.meta, dict) else {}
        brief_meta = meta.get("brief") if isinstance(meta.get("brief"), dict) else {}
        intent, research, volume, difficulty = "", "", None, None
        if art.keyword_id:
            row = s.get(KeywordLedger, art.keyword_id)
            if row is not None:
                intent = row.intent or ""
                research = row.research_snapshot or ""
                volume, difficulty = row.volume, row.difficulty
        brief = generation.build_brief_payload(
            keyword=str(meta.get("keyword") or brief_meta.get("keyword") or art.title or "").strip(),
            intent=intent, brief_meta=brief_meta,
            research_snapshot=research, volume=volume, difficulty=difficulty)
        # Real internal-link candidates for WordPress sites so even a
        # tool-skipping model can weave genuine links (checks enforce it).
        brief = _enrich_brief_with_links(art, brief, str(brief.get("keyword") or ""))

        fn = generate_fn if generate_fn is not None else _default_generate
        revise_on = os.environ.get("CONTENTFTE_REVISE", "1").strip().lower() \
            not in ("0", "off", "false", "no")
        max_attempts = 2 if revise_on else 1
        gen_started = time.time()
        gen_usage: dict = {}
        parsed = None
        checks: dict = {}
        revisions = 0
        attempt = 0
        while attempt < max_attempts:
            attempt += 1
            try:
                output = await fn(brief)
            except Exception as exc:  # runner/provider failure — fail-open
                if attempt == 1:
                    return _err(
                        f"generation failed: {exc}",
                        "check LLM keys (OPENROUTER_API_KEY / GEMINI_API_KEY / ...) "
                        "and retry generate_content")
                break
            try:
                from blog_agent import generation as agent_generation
                gen_usage = _merge_usage(
                    gen_usage, dict(getattr(agent_generation, "LAST_USAGE", None) or {}))
            except Exception:
                pass
            cand = generation.parse_generation_output(output)
            if cand is None or str(generation.get_field(cand, "status") or "").lower() == "error":
                if attempt == 1:
                    if cand is None:
                        return _err("agent returned no usable content",
                                    "retry generate_content (fallback model skipped both "
                                    "the JSON envelope and a salvageable Markdown post)")
                    message = str(generation.get_field(cand, "message") or "").strip()
                    return _err(message or "generation failed per agent envelope",
                                "fix the brief (contentfte_get_brief) and retry")
                break
            cand_content = str(generation.get_field(cand, "Generated Content") or "").strip()
            if len(cand_content) < 50:
                if attempt == 1:
                    return _err("generated content missing or too short",
                                "retry generate_content")
                break
            parsed = cand
            content = cand_content
            title = str(generation.get_field(cand, "Title") or "").strip()
            summary = str(generation.get_field(cand, "Summary") or "").strip()
            faqs = generation.parse_faqs(generation.get_field(cand, "FAQs")) \
                or generation.parse_faqs(brief_meta.get("faqs"))
            checks = _content_checks(content=content, title=title,
                                     summary=summary, faqs=faqs, brief=brief)
            if _checks_pass(checks) or attempt >= max_attempts:
                break
            # One bounded revision: feed the failing checks back verbatim.
            revisions += 1
            feedback = []
            for name, val in checks.items():
                if val.get("pass"):
                    continue
                # keyword_usage carries human-readable guidance; other checks
                # are {pass, value, need} and read fine as JSON.
                guide = val.get("guidance")
                if guide:
                    feedback.append(f"{name}: " + " ".join(guide))
                else:
                    feedback.append(f"{name}: {json.dumps(val)}")
            brief = dict(brief)
            brief["revision_feedback"] = feedback

        gen_wall_s = round(time.time() - gen_started, 1)
        if parsed is None:
            return _err("agent returned no usable content",
                        "retry generate_content")

        # HARD GATE on operator-supplied keywords: the revise loop already ran,
        # so a draft that still misses a supplied keyword is not published.
        # Reporting why is the point -- the operator sees the exact keyword,
        # its per-slot counts and where it was expected.
        kw_check = checks.get("keyword_usage") or {}
        if kw_check and not kw_check.get("pass"):
            why = " ".join(kw_check.get("guidance") or [])
            return _err(
                f"keyword gate failed after {revisions} revision(s): {why}",
                "add the missing keyword(s) to a heading and the body, then "
                "regenerate")

        previous_title = art.title
        quality = generation.parse_score(generation.get_field(parsed, "Quality Score"))
        warnings = generation.get_field(parsed, "warnings") or []
        errors = generation.get_field(parsed, "errors") or []
        claims_notes = str(generation.get_field(parsed, "Claims Notes") or "").strip()

        # Mechanical stale-year fix in the title only ("in 2025" -> current
        # year): safe because the pattern is explicit; body years are left to
        # the model instructions + the revise feedback above.
        stale_title = _stale_year_re().search(title or "")
        if stale_title:
            year = datetime.now(timezone.utc).year
            title = _stale_year_re().sub(f"in {year}", title)
            checks = _content_checks(content=content, title=title,
                                     summary=summary, faqs=faqs, brief=brief)

        if art.keyword_id:
            try:
                # Best-effort lifecycle advance (§5.16); a ledger quirk must
                # never discard a finished post (lib rule: fail-open).
                set_status(s, art.keyword_id, "drafted")
            except Exception:
                pass

        if title:
            art.title = title
        art.content_md = content
        art.status = "drafted"
        new_meta = dict(meta)
        if summary:
            new_meta["summary"] = summary
        if faqs:
            new_meta["faqs"] = faqs
        new_meta["generation"] = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "quality_score": quality,
            "regenerated": regenerate,
            "wall_s": gen_wall_s,
            "usage": gen_usage or None,
            "checks": checks,
            "revisions": revisions,
            "claims_notes": claims_notes,
            "warnings": warnings if isinstance(warnings, list) else [str(warnings)],
            "errors": errors if isinstance(errors, list) else [str(errors)],
        }
        art.meta = new_meta
        if quality is not None:
            new_meta["scores"] = {**(new_meta.get("scores") or {}), "overall": quality}
            art.meta = new_meta

        words = len(content.split())
        s.add(AuditLog(
            article_id=art.id, site_id=art.site_id, action="article.generate",
            payload={"event": "article.drafted", "keyword": meta.get("keyword"),
                     "regenerated": regenerate, "words": words,
                     "quality_score": quality, "revisions": revisions,
                     "checks_pass": _checks_pass(checks),
                     **({"title": title} if title and title != previous_title else {})}))
        s.commit()

        # §5.10-6: price the run's token usage into the per-post cost ledger
        # (models priced in lib.cost_ledger; unpriced usage records nothing).
        llm_usd = 0.0
        if gen_usage.get("input_tokens") or gen_usage.get("output_tokens"):
            try:
                llm_usd, price_detail = usage_cost(gen_usage)
                if llm_usd > 0:
                    record_cost(s, art.id, "llm", round(llm_usd, 6),
                                detail=price_detail)
            except Exception:
                llm_usd = 0.0
        return {"id": art.id, "status": art.status, "event": "article.drafted",
                "title": art.title, "words": words,
                "checks": checks, "needs_revision": not _checks_pass(checks),
                "revisions": revisions,
                **({"quality_score": quality} if quality is not None else {}),
                **({"llm_usd": round(llm_usd, 6)} if llm_usd > 0 else {})}
    finally:
        s.close()


def get_article(article_id: int, include_content: bool = False) -> dict:
    init_db()
    s = get_session()
    try:
        art = s.get(ArticleModel, article_id)
        if art is None:
            return _err(f"article {article_id} not found", "run generate_article first")
        # Normalize the stored score shape so the console's detail page and
        # the list endpoint agree (UX-03): the DB stores either
        # {"quality": N} (legacy) or {"overall": N, "sub_scores": {...}}
        # (eval-gated runs). Expose both keys plus a resolved `overall`.
        raw_scores = article_scores(art)
        normalized = dict(raw_scores)
        if "overall" not in normalized and "quality" in normalized:
            normalized["overall"] = normalized["quality"]
        if "quality" not in normalized and "overall" in normalized:
            normalized["quality"] = normalized["overall"]
        sub = normalized.get("sub_scores")
        if not isinstance(sub, dict):
            sub = {}
            normalized["sub_scores"] = sub
        # flatten sub_scores onto the top level so the console's per-subscore
        # reads (accuracy, depth, seo, voice, originality, citability) work
        for k, v in sub.items():
            normalized.setdefault(k, v)
        data: dict[str, Any] = {"id": art.id, "site_id": art.site_id, "title": art.title,
                                "slug": _resolve_slug(art), "status": art.status,
                                "scores": normalized,
                                "raw_scores": raw_scores,
                                "cost_usd": _cost_map(s, [art.id]).get(art.id, 0.0),
                                "keyword_id": art.keyword_id,
                                "word_count": len((art.content_md or "").split())
                                if (art.content_md or "").strip() else 0}
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
                date_published=_iso(art.published_at or art.created_at),
                date_modified=_modified_iso(art),
                schema_extra=_schema_extra(art, meta, brief),
                focus_keyword=_focus_keyphrase(meta, brief),
                # An operator PATCH of meta.tldr (SEO tab) wins over the
                # TL;DR block parsed from the markdown by build_delivery_payload.
                tldr=str(meta.get("tldr") or ""),
                meta_title=str(brief.get("meta_title") or ""),
                canonical=url,
                featured_image=_featured_image_ref(meta),
            )
            data.update(payload)
            data["slug"] = slug
            data["meta"] = meta
        return data
    finally:
        s.close()


def gate_enforced() -> bool:
    """QUALITY_GATE_ENFORCE=off turns the approval gate into report-only (still assessed,
    recorded and audited, never refused). Default: enforced."""
    return os.environ.get("QUALITY_GATE_ENFORCE", "1").strip().lower() not in ("0", "off", "false", "no")


def _research_corpus(s, art: ArticleModel) -> list[str]:
    """Text the fact-check may ground claims in: the keyword's stored research snapshot and the
    brief. Empty when no research was stored (the gate then warns instead of blocking)."""
    parts: list[str] = []

    def _add(v: Any) -> None:
        if v in (None, "", [], {}):
            return
        parts.append(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str))

    if art.keyword_id:
        kw = s.get(KeywordLedger, art.keyword_id)
        if kw is not None:
            _add(kw.research_snapshot)
    meta = art.meta or {}
    for key in ("research", "research_excerpts", "brief"):
        _add(meta.get(key))
    return [p for p in parts if p.strip()]


def _sibling_articles(s, art: ArticleModel, limit: int = 300) -> list[tuple]:
    """(id, title, markdown) of the SAME site's other articles that have content - what a draft is compared
    with for near-duplicate detection. Same site only: another tenant's articles are not ours to read."""
    rows = s.execute(
        select(ArticleModel.id, ArticleModel.title, ArticleModel.content_md)
        .where(ArticleModel.site_id == art.site_id, ArticleModel.id != art.id,
               ArticleModel.content_md.is_not(None), ArticleModel.status != "rejected")
        .order_by(ArticleModel.id.desc()).limit(limit)
    ).all()
    return [(r[0], r[1] or "", r[2] or "") for r in rows if (r[2] or "").strip()]


def _assess_gate(s, art: ArticleModel, check_links: bool | None = None) -> dict:
    meta = art.meta or {}
    return quality_gate.assess(
        content_md=art.content_md or "",
        meta=meta,
        source_excerpts=_research_corpus(s, art),
        faqs=meta.get("faqs"),
        check_links=check_links,
        siblings=_sibling_articles(s, art),
    )


def check_article_gate(article_id: int, check_links: bool | None = None) -> dict:
    """Read-only: run the deterministic quality gate (draft checks, fact-check against the stored
    research, eval floor, optional link check, AEO lint) and return the report. Nothing is changed."""
    init_db()
    s = get_session()
    try:
        art = s.get(ArticleModel, article_id)
        if art is None:
            return _err(f"article {article_id} not found", "run list_articles first")
        if not (art.content_md or "").strip():
            return _err(f"article {article_id} has no content yet", "run generate_content first")
        return {"id": art.id, "enforced": gate_enforced(),
                **_assess_gate(s, art, check_links)}
    finally:
        s.close()


def approve_article(article_id: int, approved: bool = True, note: str = "",
                    via: str = "api", force: bool = False) -> dict:
    """Approve (or reopen) an article.

    Approving runs the deterministic quality gate first (see lib/quality_gate.py). If it has
    blocking failures the approval is REFUSED (`code: gate_failed`) unless the caller passes
    `force=True` — an explicit, audited operator override. Reopening (`approved=False`) is never gated."""
    init_db()
    s = get_session()
    try:
        art = s.get(ArticleModel, article_id)
        if art is None:
            return _err(f"article {article_id} not found", "run generate_article first")

        if approved and art.status == "published":
            # Approving a live article used to knock it back to 'approved' (and the next publish would
            # then take the dedupe path). It is already past this gate: report, change nothing.
            return {"id": art.id, "status": art.status, "event": "article.published",
                    "note": "already published; status unchanged"}

        gate: dict | None = None
        overridden: list[str] = []
        if approved:
            gate = _assess_gate(s, art)
            if not gate["pass"]:
                if gate_enforced() and not force:
                    s.add(AuditLog(article_id=art.id, site_id=art.site_id,
                                   action="article.gate_blocked",
                                   payload={"blocking": gate["blocking"], "via": via, "note": note}))
                    s.commit()
                    return {"error": "quality gate failed: " + "; ".join(gate["blocking"][:5]),
                            "next": "fix the listed issues (edit or regenerate), or approve again with "
                                    "force=true to override (the override is audited)",
                            "code": "gate_failed", "gate": gate}
                overridden = list(gate["blocking"])
            new_meta = dict(art.meta or {})
            new_meta["gate"] = {"pass": gate["pass"], "blocking": gate["blocking"],
                                "warnings": gate["warnings"], "assessed_at": gate["assessed_at"],
                                **({"overridden": True} if overridden else {})}
            art.meta = new_meta
        art.status = "approved" if approved else "needs_review"
        s.add(AuditLog(article_id=art.id, site_id=art.site_id,
                       action="article.approve" if approved else "article.needs_review",
                       payload={"note": note, "via": via,
                                **({"gate_pass": gate["pass"], "warnings": len(gate["warnings"])}
                                   if gate else {}),
                                **({"forced": True, "overridden": overridden} if overridden else {})}))
        # Self-learning input: a dedicated review_feedback row carrying the
        # operator's note/reason (the audit row above keeps the same data, but
        # this table is what mine_feedback scans for patterns).
        s.add(ReviewFeedback(
            site_id=art.site_id, article_id=art.id, title=art.title or "",
            status="approved" if approved else "needs_review",
            score=(art.meta or {}).get("scores", {}).get("quality")
                   if isinstance((art.meta or {}).get("scores"), dict) else None,
            summary=str((art.meta or {}).get("summary") or ""),
            notes=note or "", decided_by=via or "console",
        ))
        s.commit()
        return {"id": art.id, "status": art.status,
                # Approval is not publication: the event is `article.approved`. `legacy_event` keeps the old
                # (misleading) name for one release so a consumer keyed on it keeps working (ENG-10).
                "event": "article.approved" if approved else "article.needs_review",
                **({"legacy_event": "article.published"} if approved else {}),
                **({"gate": {"pass": gate["pass"], "warnings": gate["warnings"],
                             **({"overridden": overridden} if overridden else {})}}
                   if gate else {})}
    finally:
        s.close()


def _brain_entry_to_dict(e):
    return {
        "id": e.id, "site_id": e.site_id, "kind": e.kind, "title": e.title,
        "tags": list(e.tags or []), "content": e.content, "source": e.source,
        "article_id": e.article_id,
        "created_at": _iso(e.created_at), "updated_at": _iso(e.updated_at),
    }


def list_brain_entries(site_slug="", kind=""):
    init_db()
    s = get_session()
    try:
        site, bad = _scope_site(s, site_slug, require_in_shared=True)
        if bad:
            return bad
        q = select(BrainEntry)
        if site is not None:
            q = q.where(BrainEntry.site_id == site.id)
        if kind:
            q = q.where(BrainEntry.kind == kind.strip())
        rows = s.execute(q.order_by(BrainEntry.created_at.desc())).scalars().all()
        return {"entries": [_brain_entry_to_dict(e) for e in rows], "count": len(rows)}
    finally:
        s.close()


def get_brain_entry(entry_id):
    init_db()
    s = get_session()
    try:
        e = s.get(BrainEntry, entry_id)
        if e is None:
            return _err("brain entry %d not found" % entry_id)
        return _brain_entry_to_dict(e)
    finally:
        s.close()


def create_brain_entry(site_slug="", kind="voice", title="", tags=None, content="",
                       article_id=None, source="manual"):
    init_db()
    s = get_session()
    try:
        site, bad = _scope_site(s, site_slug, require_in_shared=True)
        if bad:
            return bad   # a typo'd slug used to create a site-less entry visible to EVERY site
        if not (title or "").strip():
            return _err("title is required", "pass a title for the brain entry")
        e = BrainEntry(site_id=site.id if site else None,
                       kind=(kind or "voice").strip(), title=title.strip(),
                       tags=list(tags or []), content=content or "",
                       source=source or "manual", article_id=article_id)
        s.add(e)
        s.commit()
        s.refresh(e)
        return _brain_entry_to_dict(e)
    finally:
        s.close()


def update_brain_entry(entry_id, title=None, tags=None, content=None, kind=None):
    init_db()
    s = get_session()
    try:
        e = s.get(BrainEntry, entry_id)
        if e is None:
            return _err("brain entry %d not found" % entry_id)
        if title is not None:
            e.title = title.strip() or e.title
        if tags is not None:
            e.tags = list(tags)
        if content is not None:
            e.content = content
        if kind is not None and kind.strip():
            e.kind = kind.strip()
        s.commit()
        s.refresh(e)
        return _brain_entry_to_dict(e)
    finally:
        s.close()


def delete_brain_entry(entry_id):
    init_db()
    s = get_session()
    try:
        e = s.get(BrainEntry, entry_id)
        if e is None:
            return _err("brain entry %d not found" % entry_id)
        s.delete(e)
        s.commit()
        return {"deleted": entry_id}
    finally:
        s.close()


def get_brain_notes(topic="", site_slug=""):
    """Brain notes for a topic. These are injected into the writer's prompt, so on an engine that
    serves several sites they must come ONLY from that site: the site-less ("global") rows and the
    repo's brain/*.md files belong to the operator's own site and are not shared with tenants
    (plan ENG-08 -- one tenant's first-hand stories used to surface in another tenant's draft)."""
    from lib.site_env import is_shared_mode
    shared = is_shared_mode()
    init_db()
    s = get_session()
    try:
        site, bad = _scope_site(s, site_slug, require_in_shared=True)
        if bad:
            return bad
        q = select(BrainEntry)
        if site is not None:
            cond = BrainEntry.site_id == site.id
            q = q.where(cond if shared else (cond | BrainEntry.site_id.is_(None)))
        rows = s.execute(q).scalars().all()
        db_entries = [{"title": e.title, "tags": list(e.tags or []),
                       "content": e.content, "kind": e.kind} for e in rows]
    finally:
        s.close()

    file_entries = []
    try:
        from pathlib import Path
        brain_dir = Path(__file__).resolve().parents[1] / "brain"
        if brain_dir.is_dir() and not shared:
            for pp in sorted(brain_dir.glob("*.md")):
                if pp.name == "README.md" or pp.name.startswith("_"):
                    continue
                try:
                    text = pp.read_text(encoding="utf-8")
                except Exception:
                    continue
                title = ""
                tags = []
                for line in text.splitlines()[:12]:
                    sl = line.strip()
                    if sl.startswith("# ") and not title:
                        title = sl[2:].strip()
                    if sl.lower().startswith("tags:"):
                        tags = [t.strip() for t in sl[5:].split(",") if t.strip()]
                file_entries.append({"title": title or pp.stem, "tags": tags,
                                    "content": text, "kind": "voice",
                                    "source_file": pp.name})
    except Exception:
        pass

    seen = {e["title"] for e in db_entries}
    for fe in file_entries:
        if fe["title"] not in seen:
            db_entries.append(fe)
            seen.add(fe["title"])

    topic_l = (topic or "").lower()
    matched = []
    for e in db_entries:
        haystack = " ".join([e["title"]] + (e.get("tags") or []) + [e.get("content", "")[:200]]).lower()
        if not topic_l or any(w in haystack for w in topic_l.split() if len(w) > 3):
            matched.append(e)
    matched.sort(key=lambda e: 0 if e.get("kind") == "voice" else 1)
    combined = "\n\n---\n\n".join(
        "# %s\nTags: %s\n\n%s" % (e["title"], ", ".join(e.get("tags") or []), e["content"])
        for e in matched
    )
    return {"topic": topic, "matches": len(matched), "entries": matched, "text": combined}


def log_coverage(article_id):
    init_db()
    s = get_session()
    try:
        art = s.get(Article, article_id) if False else s.get(ArticleModel, article_id)
        if art is None:
            return _err("article %d not found" % article_id)
        if art.status not in ("approved", "published"):
            return _err("article %d is %r - coverage only for approved/published" % (article_id, art.status))
        title = art.title or ("#%d" % art.id)
        tags = [w.lower() for w in (title or "").split() if len(w) > 3][:8]
        summary = str((art.meta or {}).get("summary") or "")
        sc = (art.meta or {}).get("scores")
        score = sc.get("quality") if isinstance(sc, dict) else None
        content = ("Auto-logged coverage record (not personal voice).\n"
                   "Approved: %s\nQuality score: %s\nSummary: %s\n"
                   % (__import__("datetime").datetime.now(__import__("datetime").timezone.utc).date().isoformat(),
                      score, summary))
        e = BrainEntry(site_id=art.site_id, kind="coverage", title=title,
                       tags=tags, content=content, source="auto_coverage",
                       article_id=art.id)
        s.add(e)
        s.commit()
        s.refresh(e)
        return _brain_entry_to_dict(e)
    finally:
        s.close()


def mine_feedback(site_slug="", min_rows=5):
    init_db()
    s = get_session()
    try:
        site, bad = _scope_site(s, site_slug, require_in_shared=True)
        if bad:
            return bad
        q = select(ReviewFeedback)
        if site is not None:
            q = q.where(ReviewFeedback.site_id == site.id)
        rows = s.execute(q.order_by(ReviewFeedback.decided_at.desc())).scalars().all()
        if len(rows) < min_rows:
            return {"status": "insufficient_data", "rows": len(rows),
                    "min_rows": min_rows,
                    "message": "need more approve/reject decisions before mining"}
        rejected = [r for r in rows if r.status in ("rejected", "needs_review")]
        approved = [r for r in rows if r.status == "approved"]
        proposals = []
        if rejected:
            from collections import Counter
            words = Counter()
            for r in rejected:
                for w in (r.notes or "").lower().split():
                    if len(w) > 4:
                        words[w] += 1
            top = [w for w, n in words.most_common(5) if n >= 2]
            if top:
                proposals.append({"kind": "voice", "title": "Recurring rejection themes",
                                 "tags": top,
                                 "content": ("Candidate (operator must author the real entry):\n"
                                             "Rejection notes most often mention: " + ", ".join(top) +
                                             ". Based on %d rejected rows." % len(rejected))})
        proposals.append({"kind": "coverage", "title": "Approval summary",
                          "tags": ["approval", "stats"],
                          "content": "Approved: %d, rejected/needs_review: %d (of %d total)."
                                     % (len(approved), len(rejected), len(rows))})
        return {"status": "ok", "rows_scanned": len(rows),
                "approved": len(approved), "rejected": len(rejected),
                "proposals": proposals,
                "note": "proposals only - nothing is written to brain_entries automatically"}
    finally:
        s.close()


def list_review_feedback(site_slug="", limit=100):
    init_db()
    limit = _clamp_limit(limit, 100)
    s = get_session()
    try:
        site, bad = _scope_site(s, site_slug, require_in_shared=True)
        if bad:
            return bad
        q = select(ReviewFeedback)
        if site is not None:
            q = q.where(ReviewFeedback.site_id == site.id)
        rows = s.execute(q.order_by(ReviewFeedback.decided_at.desc()).limit(limit)).scalars().all()
        return {"items": [{"id": r.id, "site_id": r.site_id, "article_id": r.article_id,
                           "title": r.title, "status": r.status, "score": r.score,
                           "summary": r.summary, "notes": r.notes,
                           "decided_by": r.decided_by, "decided_at": _iso(r.decided_at)}
                          for r in rows], "count": len(rows)}
    finally:
        s.close()


def update_content(article_id: int, content_md: str, note: str = "",
                   via: str = "api") -> dict:
    """Operator edit of an article's markdown (console PATCH /articles/{id}/content).

    - Every edit is appended to `meta["edit_log"]` and audit-logged.
    - An `approved` article is reopened to `generated` so the approve gate
      runs again on the edited text; a `published` one keeps its status
      (the live post changes on the next refresh).
    - The quality gate is NOT re-run here -- regenerating is the path for
      a full re-score; an edit is a human override."""
    init_db()
    s = get_session()
    try:
        art = s.get(ArticleModel, article_id)
        if art is None:
            return _err(f"article {article_id} not found", "run generate_article first")
        if not (content_md or "").strip():
            return _err("content_md is empty", "send the full replacement markdown")
        reopened = art.status == "approved"
        previous_md = art.content_md or ""
        art.content_md = content_md
        if reopened:
            art.status = "generated"
        from lib import freshness
        meta = freshness.bump_modified(art.meta or {}, previous_md, content_md)
        meta["edit_log"] = [
            *(meta.get("edit_log") or []),
            {"at": datetime.now(timezone.utc).isoformat(), "note": note, "via": via},
        ]
        art.meta = meta  # assign-before-commit (JSON in-place mutation fix)
        s.add(AuditLog(article_id=art.id, site_id=art.site_id,
                       action="article.edit",
                       payload={"note": note, "via": via,
                                "reopened": reopened,
                                "chars": len(content_md)}))
        s.commit()
        return {"id": art.id, "status": art.status, "reopened": reopened,
                "edits": len(meta["edit_log"]), "event": "article.edited"}
    finally:
        s.close()


_META_FIELD_LIMITS = {"title": 300, "slug": 200, "focus_keyword": 200, "summary": 2000, "tldr": 1500}


def patch_article_meta(article_id: int, fields: dict[str, str]) -> dict:
    """Operator PATCH of allowed meta fields (title / slug / focus_keyword / summary / tldr).

    - Only allowlisted keys are applied; every other meta key stays untouched.
    - Every edit is appended to ``meta["edit_log"]`` and audit-logged.
    - An ``approved`` article is reopened to ``generated`` so the approve gate
      can re-run on the new fields; a ``published`` article keeps its status
      (the live post changes on the next refresh).
    - Returns the updated article dict (same shape as ``get_article`` without
      ``include_content=True``).
    """
    init_db()
    s = get_session()
    try:
        art = s.get(ArticleModel, article_id)
        if art is None:
            return _err(f"article {article_id} not found", "run list_articles first")
        if not isinstance(fields, dict) or not fields:
            return _err("no allowlisted fields supplied (fields dict is empty)", "send at least one of title,slug,focus_keyword,summary,tldr")
        too_long = [k for k, limit in _META_FIELD_LIMITS.items()
                    if k in fields and len(str(fields[k] if fields[k] is not None else "")) > limit]
        if too_long:
            return _err(f"invalid value: {', '.join(too_long)} too long "
                        f"(max {', '.join(f'{k}={_META_FIELD_LIMITS[k]}' for k in too_long)} chars)",
                        "shorten the field and retry")
        meta = dict(art.meta) if isinstance(art.meta, dict) else {}
        brief = meta.get("brief") if isinstance(meta.get("brief"), dict) else {}
        changed: list[str] = []
        # --- title ---
        if "title" in fields and str(fields["title"]).strip():
            art.title = str(fields["title"]).strip()
            changed.append("title")
        # --- slug ---
        if "slug" in fields and str(fields["slug"]).strip():
            art.slug = str(fields["slug"]).strip()
            changed.append("slug")
        # --- focus_keyword (stored as brief.keyword — what the page writes for) ---
        if "focus_keyword" in fields and str(fields["focus_keyword"]).strip():
            brief["keyword"] = str(fields["focus_keyword"]).strip()
            meta["brief"] = brief
            changed.append("focus_keyword")
        # --- summary ---
        if "summary" in fields and str(fields["summary"]).strip():
            meta["summary"] = str(fields["summary"]).strip()
            changed.append("summary")
        # --- tldr ---
        if "tldr" in fields and str(fields["tldr"]).strip():
            meta["tldr"] = str(fields["tldr"]).strip()
            changed.append("tldr")
        if not changed:
            return _err("no allowlisted fields supplied or all empty",
                        "send at least one of title,slug,focus_keyword,summary,tldr")
        # --- edit_log (mirrors update_content pattern) ---
        meta["edit_log"] = [*(meta.get("edit_log") or []), {
            "at": datetime.now(timezone.utc).isoformat(),
            "note": "meta edit via PATCH /sdk/v1/articles/{id}/meta",
            "via": "api",
            "fields": changed,
        }]
        # --- reopen approved (mirrors update_content); published keeps status ---
        reopened = art.status == "approved"
        if reopened:
            art.status = "generated"
        art.meta = meta  # assign-before-commit (JSON in-place mutation fix)
        s.add(AuditLog(article_id=art.id, site_id=art.site_id,
                       action="article.meta_edit",
                       payload={"via": "api", "fields": changed,
                                "reopened": reopened}))
        s.commit()
        # --- return updated article dict (same shape as get_article w/o content) ---
        data: dict[str, Any] = {"id": art.id, "site_id": art.site_id,
                                "title": art.title, "slug": _resolve_slug(art),
                                "status": art.status,
                                "scores": article_scores(art),
                                "cost_usd": _cost_map(s, [art.id]).get(art.id, 0.0),
                                "keyword_id": art.keyword_id,
                                "meta": meta}
        return data
    finally:
        s.close()


def _str_list(raw: Any) -> list[str]:
    """Brief/meta list field -> [str, ...] (tolerates a single string)."""
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [str(v).strip() for v in raw if str(v or "").strip()]


def _download_image(url: str) -> str | None:
    """Remote image -> local temp file (WP media upload needs bytes). Fail-open."""
    try:
        import requests
        from tempfile import NamedTemporaryFile

        from lib import image_format

        resp = safe_get(url, timeout=30)
        resp.raise_for_status()
        suffix = image_format.sniff_ext(resp.content, fallback=".jpg")
        with NamedTemporaryFile(delete=False, suffix=suffix) as fh:
            fh.write(resp.content)
            return fh.name
    except Exception:  # noqa: BLE001 — an unusable source skips the image
        return None


def _featured_image_ref(meta: dict) -> dict | None:
    """The article's featured image as {url, alt, width, height} for the delivery payload - only an image that
    already has a public http(s) URL (a local staging path is not something a remote site can load)."""
    rows = meta.get("images") if isinstance(meta, dict) else None
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, dict) or str(row.get("slot") or "").strip().lower() == "inpost":
            continue
        url = str(row.get("url") or row.get("image_url") or "").strip()
        if url.startswith(("http://", "https://")):
            ref = {"url": url, "alt": str(row.get("alt") or row.get("alt_text") or "").strip()}
            for k in ("width", "height"):
                try:
                    if row.get(k):
                        ref[k] = int(row[k])
                except (TypeError, ValueError):
                    pass
            return ref
    return None


def _wp_images(meta: dict) -> tuple[str | None, str, list[dict], list[str]]:
    """meta.images -> (featured_path, featured_alt, inpost_images, temp_paths).

    Accepts the sheet-mirror / image-pipeline rows
    {slot, url|path|image_url, alt|alt_text, after_h2}. A featured row with a
    remote URL is downloaded once (upload_media needs bytes); in-post rows
    keep remote URLs as-is (publish() injects them directly). Fail-open:
    unusable rows are skipped, never raised.
    """
    rows = meta.get("images")
    if not isinstance(rows, list):
        return None, "", [], []
    featured_path: str | None = None
    featured_alt = ""
    temps: list[str] = []
    inpost: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        src = str(row.get("path") or row.get("url") or row.get("image_url") or "").strip()
        alt = str(row.get("alt") or row.get("alt_text") or "").strip()
        if not src:
            continue
        slot = str(row.get("slot") or "").strip().lower()
        try:
            after_h2: int | None = int(row.get("after_h2")) if row.get("after_h2") is not None else None
        except (TypeError, ValueError):
            after_h2 = None
        if slot == "inpost":
            if os.path.isfile(src):
                inpost.append({"path": src, "alt": alt, "after_h2": after_h2})
            elif src.startswith(("http://", "https://")):
                inpost.append({"url": src, "alt": alt, "after_h2": after_h2})
            continue
        if featured_path is not None:
            continue
        # "featured" slot, or the first non-inpost row when no slot was recorded
        if os.path.isfile(src):
            featured_path, featured_alt = src, alt
        elif src.startswith(("http://", "https://")):
            local = _download_image(src)
            if local:
                featured_path, featured_alt = local, alt
                temps.append(local)
    return featured_path, featured_alt, inpost, temps


def _article_taxonomy(conn, art: ArticleModel, meta: dict, brief: dict) -> dict:
    """Categories/tags for the WP push (§5.11) — derived once and cached in
    `meta["taxonomy"]` so publish and later refreshes apply the SAME terms.

    Precedence (per lib.taxonomy): publisher brief/meta wins; else prefer-
    reuse against the site's existing categories (conn.list_terms, fail-open)
    → JEV Choice judge when lexical found nothing confident (env-gated via
    OPENROUTER_API_KEY, swallowed on any failure) → title-cased propose-new.
    The Article path submits title-only briefs, so without this every post
    would land on the default category with zero tags."""
    cached = meta.get("taxonomy")
    if isinstance(cached, dict) and (cached.get("categories") or cached.get("tags")):
        return cached
    keyword = (str(meta.get("keyword") or "").strip()
               or str(brief.get("keyword") or "").strip())
    existing: list[str] = []
    # Only read the site's taxonomy when we have to decide ourselves —
    # publisher-supplied categories make the prefer-reuse input moot.
    if not (_str_list(brief.get("categories")) or _str_list(meta.get("categories"))):
        try:
            existing = conn.list_terms("categories") or []
        except Exception:  # noqa: BLE001 — prefer-reuse input is best-effort
            existing = []
    tax = derive_taxonomy(keyword=keyword, title=art.title or "", brief=brief,
                          meta=meta, existing_categories=existing)
    meta["taxonomy"] = tax
    return tax


def _wp_push(art: ArticleModel, meta: dict, mode: str) -> dict:
    """§5.11 WordPress push for site_type=wordpress — best-effort, never raises.

    Builds the PreparedPost from the Article (blocks render target: meta
    description, Article+FAQ JSON-LD, Yoast/RankMath/AIOSEO meta, categories
    + tags via _article_taxonomy (brief override, else prefer-reuse/JEV/
    propose-new — cached in meta["taxonomy"], default category only as the
    last-resort safety net), featured/in-post images from meta.images) and
    publishes through WordPressConnector. The status flip already happened —
    a WP failure only appends {"ok": false, ...} so the operator can fix and
    re-run; meta.wp_post_id dedupes a created post.
    """
    from lib.wordpress import WPConfig, WordPressConnector, build_prepared_post

    cfg = _wp_config(art.site)
    if not (cfg.base_url and cfg.username and cfg.app_password):
        return {"ok": False, "error": "WordPress not configured",
                "next": "set WP_BASE_URL, WP_USERNAME, WP_APP_PASSWORD (or "
                        "Site.settings.wp)"}
    if not (art.content_md or "").strip():
        return {"ok": False, "error": "article has no content_md",
                "next": "run contentfte_generate_article / generate_content first"}
    if meta.get("wp_post_id"):
        return {"ok": True, "deduplicated": True, "post_id": int(meta["wp_post_id"]),
                "url": str(meta.get("wp_url") or ""),
                "next": "already pushed to WordPress — edit in WP or use the "
                        "elementor ops / a WP-refresh instead of re-publishing"}

    brief = meta.get("brief") if isinstance(meta.get("brief"), dict) else {}
    slug = _resolve_slug(art)
    base = ((art.site.base_url if art.site is not None else "") or "").strip().rstrip("/")
    url = f"{base}/{slug}" if base else ""
    featured_path, featured_alt, inpost, temps = _wp_images(meta)
    try:
        conn = WordPressConnector(cfg)
        tax = _article_taxonomy(conn, art, meta, brief)
        post = build_prepared_post(
            title=art.title or slug,
            markdown=art.content_md,
            url=url,
            faqs=_parse_faqs(meta.get("faqs") or brief.get("faqs")),
            categories=tax["categories"],
            tags=tax["tags"],
            meta_title=str(brief.get("meta_title") or ""),
            meta_description=str(brief.get("description") or meta.get("summary") or ""),
            canonical=url,
            slug=slug,
            featured_image_path=featured_path,
            featured_alt=featured_alt,
            inpost_images=inpost,
            cta=brief.get("cta") if isinstance(brief.get("cta"), dict) else None,
            entities=brief.get("entities") if isinstance(brief.get("entities"), list) else None,
            date_published=_iso(art.published_at or art.created_at),
            date_modified=_modified_iso(art),
            schema_extra=_schema_extra(art, meta, brief),
            focus_keyphrase=_focus_keyphrase(meta, brief),
            render_target="blocks",
        )
        if not post.categories:
            fallback = conn.default_category()
            if fallback:
                post.categories = [fallback]
        result = conn.publish(post, mode=mode)
    except Exception as exc:  # noqa: BLE001 — the push never fails the publish
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                "next": "fix WP config / outbound links / site reachability, then "
                        "re-run publish (the article stays published; the push is retried)"}
    finally:
        for tmp in temps:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    out: dict[str, Any] = {"ok": True, "post_id": result["id"],
                           "url": result.get("url", ""),
                           "status": result.get("status", ""),
                           "slug": result.get("slug", ""),
                           "categories": list(post.categories),
                           "tags": list(post.tags),
                           "category_source": tax.get("category_source", ""),
                           "render_target": "blocks"}
    if result.get("featured_media"):
        out["featured_media"] = result["featured_media"]
    return out


_inflight_lock = threading.Lock()
_inflight: set[tuple[str, int]] = set()


def _claim(kind: str, article_id: int) -> bool:
    """Take the single-flight slot for (operation, article). False if one is already running in this
    process. A double-clicked Publish, or a console retry while the first call is still in flight,
    used to run twice and create two WordPress posts (the id was only saved AFTER the remote create);
    two concurrent generations both ran the LLM and both wrote (plan ENG-03 / ENG-04). Across
    processes too: the claim is mirrored in the `leases` table (lib/lease.py), which expires, so a killed
    worker cannot wedge an article."""
    with _inflight_lock:
        key = (kind, int(article_id))
        if key in _inflight:
            return False
        _inflight.add(key)
    # Cross-process: the same claim in the database, so a second uvicorn worker (or a pipeline process) cannot
    # run the same publish/generation. None = the table is unusable -> keep only the process-local guard.
    from lib import lease
    held = lease.claim(f"{kind}:{int(article_id)}")
    if held is False:
        with _inflight_lock:
            _inflight.discard(key)
        return False
    return True


def _release(kind: str, article_id: int) -> None:
    with _inflight_lock:
        _inflight.discard((kind, int(article_id)))
    from lib import lease
    lease.release(f"{kind}:{int(article_id)}")


def publish_article(article_id: int, mode: str = "draft", via: str = "api",
                    force: bool = False, enforce_cadence: bool = False) -> dict:
    """Publish decision (§5.11 draft default). Requires approved status. One publish per article at a
    time: a concurrent call returns `code: publish_in_progress` instead of racing the first."""
    if not _claim("publish", article_id):
        return {"error": f"article {article_id} is already being published",
                "next": "wait for the current publish to finish, then re-check the article's status",
                "code": "publish_in_progress"}
    try:
        return _publish_article_locked(article_id, mode=mode, via=via, force=force,
                                       enforce_cadence=enforce_cadence)
    finally:
        _release("publish", article_id)


def _publish_article_locked(article_id: int, mode: str = "draft", via: str = "api",
                            force: bool = False, enforce_cadence: bool = False) -> dict:
    """Publish decision (§5.11 draft default). Requires approved status.

    WordPress sites (site_type="wordpress") additionally push the article to
    WP in this same call — zero manual steps: approve -> publish -> post in
    WP with meta description, Article+FAQ JSON-LD, categories and the
    featured/in-post images. Best-effort fail-open: the status flip and cost
    finalization always succeed; the push outcome rides along as
    {"wp": {...}} and never raises (re-running publish retries the push).
    """
    init_db()
    s = get_session()
    try:
        art = s.get(ArticleModel, article_id)
        if art is None:
            return _err(f"article {article_id} not found", "run generate_article first")

        site = art.site
        if site is not None:
            cadence = get_site_cadence_status(s, site)
            if cadence.get("require_approval", True) and art.status not in ("approved", "published"):
                return _err(
                    f"article {article_id} is '{art.status}' — publish requires 'approved' (operator approval required by site cadence settings)",
                    "gate: approve the article in the console or via POST /sdk/v1/articles/{id}/approve")
            # Enforcement is opt-in per call OR per site (Site.settings["enforce_cadence"]); the
            # console never sent the per-call flag, so the cadence it shows was advisory only.
            if (enforce_cadence or cadence.get("enforced")) and not force \
                    and not cadence.get("can_publish_now", True):
                next_time = cadence.get("next_allowed_at")
                freq = cadence.get("frequency")
                hours = round((cadence.get("seconds_remaining") or 0) / 3600, 1)
                return _err(
                    f"cadence limit reached for site '{site.slug}': {cadence.get('posts_in_window')} of "
                    f"{cadence.get('max_posts_per_cadence')} allowed post(s) already went out this '{freq}' "
                    f"window. Next slot opens at {next_time} ({hours}h remaining)",
                    "wait for cadence window or pass force=true to override")

        if art.status not in ("approved", "published"):
            return _err(
                f"article {article_id} is '{art.status}' — publish requires 'approved'",
                "gate: overall >=90 and every sub-score >=80, then POST /sdk/v1/articles/{id}/approve")
        art.status = "published"
        if art.published_at is None:
            art.published_at = datetime.now(timezone.utc)
        # §5.10-6 finalize the per-post cost ledger at publish. Spend is read
        # back from the ledger on demand — no denormalized cost_usd copy.
        totals = finalize(s, art.id)

        meta = dict(art.meta) if isinstance(art.meta, dict) else {}
        wp_state: dict | None = None
        site_type = (art.site.site_type if art.site is not None else "") or ""
        if site_type == "wordpress":
            # §5.9 first-try images: if the generator never staged any
            # (single-shot models skip _image_plan), generate them here so
            # the very first publish already carries featured + inline art.
            staging = _stage_images_for(art, meta, reason="publish")
            if meta.get("images"):
                meta["image_staging"] = {k: staging.get(k)
                                         for k in ("reason", "featured", "inpost",
                                                   "errors", "skipped")
                                         if staging.get(k) is not None}
                # §5.10-6 price AI image generations into the same ledger
                # (once — retries see image_costs_recorded and skip).
                img_usd = 0.0
                if not meta.get("image_costs_recorded"):
                    img_usd = sum(float(r.get("cost_usd") or 0.0)
                                  for r in (meta.get("images") or [])
                                  if isinstance(r, dict))
                    meta["image_costs_recorded"] = True
                # Single assignment AFTER every mutation so the staged rows
                # persist even if the push below fails, and record_cost's
                # commit flushes meta together with its ledger row. (Mutating
                # `meta` in place after an earlier commit is invisible to
                # SQLAlchemy: the in-memory committed object mutates too, so
                # history shows no net change and the UPDATE never fires.)
                art.meta = dict(meta)
                if img_usd > 0:
                    try:
                        record_cost(s, art.id, "image", round(img_usd, 6),
                                    detail={"slots": len(meta["images"]),
                                            "reason": "publish staging"})
                    except Exception:
                        pass
            wp_state = _wp_push(art, meta, mode)
            if wp_state.get("ok") and wp_state.get("post_id") and not wp_state.get("deduplicated"):
                meta["wp_post_id"] = wp_state["post_id"]
                meta["wp_url"] = wp_state.get("url") or ""
                art.meta = dict(meta)

        payload: dict[str, Any] = {"mode": mode, "via": via}
        if wp_state is not None:
            payload["wp"] = wp_state
        if meta.get("image_staging"):
            payload["image_staging"] = meta["image_staging"]
        s.add(AuditLog(article_id=art.id, site_id=art.site_id,
                       action="article.publish", payload=payload))
        s.commit()
        out: dict[str, Any] = {"id": art.id, "status": art.status, "mode": mode,
                               "cost_usd": totals["total_usd"], "event": "article.published"}
        if wp_state is not None:
            out["wp"] = wp_state
        elif site_type != "wordpress":
            delivery = _deliver_to_custom_site(art)
            if delivery is not None:
                out["delivery"] = delivery
        # §5.6 concrete URL submission (IndexNow + Bing WMT) — best-effort,
        # after the status flip; a ping failure never fails the publish.
        live_url = str((wp_state or {}).get("url") or "")
        base_url = ((art.site.base_url if art.site is not None else "") or "").strip()
        if not live_url and base_url:
            live_url = f"{base_url.rstrip('/')}/{_resolve_slug(art)}"
        if live_url and not _is_live(wp_state, mode):
            # A WordPress draft (or a failed push) has no public URL: pinging search engines about it
            # trains them to distrust the site's submissions and wastes the daily IndexNow quota (ENG-20).
            out["indexing"] = {"url": live_url, "skipped": "not live yet - published as a WordPress "
                               "draft, or the push failed; it is submitted when the post goes live"}
        elif live_url:
            from lib.indexing import submit_published
            try:
                out["indexing"] = submit_published(live_url, site_url=base_url,
                                                   **_indexing_keys(art.site))
            except Exception:  # noqa: BLE001 — never raise from a ping
                out["indexing"] = {"url": live_url, "error": "submission failed"}
        return out
    finally:
        s.close()


_DELIVERY_KEYS = ("title", "slug", "url", "excerpt", "html", "markdown", "markdown_alternate",
                  "faq_html", "schema", "seo")


def _delivery_target(site) -> tuple[str, str]:
    """(webhook_url, signing_secret) for a custom site: its own `Site.settings.delivery`, else - for a
    single-site instance only - SITE_PUBLISH_WEBHOOK / SITE_PUBLISH_SECRET. In shared mode a process-global
    URL would push every tenant's articles to one site, so it is not used."""
    group = ((getattr(site, "settings", None) or {}).get("delivery")) if site is not None else None
    group = group if isinstance(group, dict) else {}
    url, secret = str(group.get("webhook_url") or "").strip(), str(group.get("secret") or "").strip()
    if not url:
        from lib.site_env import is_shared_mode
        if not is_shared_mode():
            url = (os.environ.get("SITE_PUBLISH_WEBHOOK") or "").strip()
            secret = secret or (os.environ.get("SITE_PUBLISH_SECRET") or "").strip()
    return url, secret


def _deliver_to_custom_site(art: ArticleModel) -> dict | None:
    """Push the rendered article to a custom site's publish webhook when one is configured (ADP-04).
    Signed, retried, idempotent by delivery id. Returns None when nothing is configured (the pull route
    `GET /articles/{id}/content` is still the default); never raises, never fails the publish."""
    url, secret = _delivery_target(art.site)
    if not url:
        return None
    try:
        data = get_article(art.id, include_content=True)
        payload = {k: data.get(k) for k in _DELIVERY_KEYS if k in data}
        payload["article_id"] = art.id
        payload["event"] = "article.published"
        res = custom_site.deliver(payload, webhook_url=url, secret=secret)
        s = get_session()
        try:
            s.add(AuditLog(article_id=art.id, site_id=art.site_id, action="article.delivery",
                           payload={k: res.get(k) for k in ("status", "status_code", "attempts", "delivery_id",
                                                             "signed", "message") if k in res}))
            s.commit()
        finally:
            s.close()
        return res
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": f"{type(exc).__name__}: {exc}"}


def _indexing_keys(site) -> dict:
    """This site's own IndexNow / Bing keys (Site.settings["indexing"]) as submit_published kwargs."""
    group = ((getattr(site, "settings", None) or {}).get("indexing")) if site is not None else None
    group = group if isinstance(group, dict) else {}
    return {"indexnow_key": str(group.get("indexnow_key") or ""),
            "bing_key": str(group.get("bing_wmt_key") or "")}


def _is_live(wp_state: dict | None, mode: str) -> bool:
    """Whether the publish put a PUBLIC page online, i.e. whether submitting its URL is meaningful.

    Custom sites have no push (the article is served by the site itself), so they count as live as before.
    For WordPress only a post that really went to the `publish` status counts; a draft, a failed push, and
    a deduplicated re-run (status unknown) are live only when this call asked for `auto`."""
    if wp_state is None:
        return True
    if not wp_state.get("ok"):
        return False
    status = str(wp_state.get("status") or "").lower()
    if status:
        return status == "publish"
    return mode in ("auto", "publish")


def _render_wp_body(conn, post) -> str:
    """Assemble a WordPress body for an EXISTING post: upload in-post images
    that are local paths, inject at their H2 anchors, append Article+FAQ
    JSON-LD. Mirrors the publish() body assembly for the refresh path."""
    from lib import wp_render

    uploaded = []
    for img in post.inpost_images:
        src = img.get("url") or img.get("src")
        if not src and img.get("path"):
            src = conn.upload_media(img["path"], img.get("alt", ""))["url"]
        if src:
            uploaded.append({"url": src, "alt": img.get("alt", ""),
                             "after_h2": img.get("after_h2")})
    body = wp_render.inject_inpost_images(post.html, uploaded)
    body += "\n" + wp_render.jsonld_script(post.article_schema)
    if post.faq_schema:
        body += "\n" + wp_render.jsonld_script(post.faq_schema)
    return body


def refresh_article(article_id: int, via: str = "api") -> dict:
    """Refresh an already-published article on its site (§5.11 decay path).

    WordPress (site_type="wordpress"): updates the EXISTING post in place —
    content + SEO meta + taxonomy + optional featured image — never creates a
    post and never changes its status (a refresh must not un-publish).
    Taxonomy follows publish: brief/meta override else the cached
    `meta["taxonomy"]` (derived on first publish), so a refresh re-applies
    the exact same categories/tags. Requires `meta.wp_post_id` (publish).

    Custom sites have no push: this re-renders the article and tells the caller
    to re-pull `GET /sdk/v1/articles/{id}/content` (or re-deliver the payload).
    """
    init_db()
    s = get_session()
    try:
        art = s.get(ArticleModel, article_id)
        if art is None:
            return _err(f"article {article_id} not found", "run generate_article first")
        if not (art.content_md or "").strip():
            return _err(f"article {article_id} has no content",
                        "run generate_content first")
        meta = dict(art.meta) if isinstance(art.meta, dict) else {}
        site_type = (art.site.site_type if art.site is not None else "") or ""
        if site_type != "wordpress":
            return {"article_id": art.id, "ok": True, "event": "article.refreshed",
                    "render_target": "custom",
                    "next": "custom sites have no push — re-pull "
                            f"GET /sdk/v1/articles/{art.id}/content (or re-deliver "
                            "the payload to the site)"}
        post_id = meta.get("wp_post_id")
        if not post_id:
            return _err(f"article {article_id} has no wp_post_id",
                        "publish it first — the WP post id is stored on publish")

        from lib.wordpress import WPConfig, WordPressConnector, build_prepared_post

        cfg = _wp_config(art.site)
        if not (cfg.base_url and cfg.username and cfg.app_password):
            return _err("WordPress not configured",
                        "set WP_BASE_URL, WP_USERNAME, WP_APP_PASSWORD")
        brief = meta.get("brief") if isinstance(meta.get("brief"), dict) else {}
        slug = _resolve_slug(art)
        base = ((art.site.base_url if art.site is not None else "") or "").strip().rstrip("/")
        url = f"{base}/{slug}" if base else ""
        featured_path, featured_alt, inpost, temps = _wp_images(meta)
        is_elementor = str(meta.get("render_target") or "").lower() == "elementor"
        try:
            conn = WordPressConnector(cfg)
            tax = _article_taxonomy(conn, art, meta, brief)
            post = build_prepared_post(
                title=art.title or slug,
                markdown=art.content_md,
                url=url,
                faqs=_parse_faqs(meta.get("faqs") or brief.get("faqs")),
                categories=tax["categories"],
                tags=tax["tags"],
                meta_title=str(brief.get("meta_title") or ""),
                meta_description=str(brief.get("description") or meta.get("summary") or ""),
                canonical=url,
                slug=slug,
                featured_image_path=featured_path,
                featured_alt=featured_alt,
                inpost_images=inpost,
                cta=brief.get("cta") if isinstance(brief.get("cta"), dict) else None,
                entities=brief.get("entities") if isinstance(brief.get("entities"), list) else None,
                date_published=_iso(art.published_at or art.created_at),
                date_modified=_modified_iso(art),
                schema_extra=_schema_extra(art, meta, brief),
                focus_keyphrase=_focus_keyphrase(meta, brief),
                render_target="elementor" if is_elementor else "blocks",
            )
            body = _render_wp_body(conn, post)
            res = conn.update_post(int(post_id), post, body_html=body,
                                   featured_image_path=featured_path)
            if is_elementor:
                # An Elementor page renders from `_elementor_data`, NOT from post_content: updating only the
                # content left the visible page stale (ADP-09). Rewrite the document from the new content.
                from lib import wp_render
                from lib.elementor import ElementorClient, build_blog_page_data
                elementor_body = post.html + "\n" + wp_render.jsonld_script(post.article_schema)
                if post.faq_schema:
                    elementor_body += "\n" + wp_render.jsonld_script(post.faq_schema)
                res["elementor"] = ElementorClient(cfg).save_document(
                    int(post_id), build_blog_page_data(post.title, elementor_body, faqs=post.faqs),
                    page_settings={"hide_title": "yes"})
        except Exception as exc:  # noqa: BLE001 — refresh never raises
            return _err(f"wp refresh failed: {type(exc).__name__}: {exc}",
                        "check WP config / reachability, then re-run refresh")
        finally:
            for tmp in temps:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        # Assign-before-commit: persists the cached meta["taxonomy"] decided
        # above (in-place mutation after an earlier commit would be invisible
        # to SQLAlchemy — same pattern as publish_article).
        art.meta = dict(meta)
        s.add(AuditLog(article_id=art.id, site_id=art.site_id, action="article.refresh",
                       payload={"wp_post_id": int(post_id), "via": via,
                                "url": res.get("url", ""),
                                "categories": list(post.categories),
                                "tags": list(post.tags)}))
        s.commit()
        # §5.6 re-ping after an in-place refresh (updated content +
        # dateModified bump) — same fail-open contract as publish.
        indexing: dict = {}
        if res.get("url"):
            from lib.indexing import submit_published
            try:
                indexing = submit_published(res["url"], site_url=base, **_indexing_keys(art.site))
            except Exception:  # noqa: BLE001 — never raise from a ping
                indexing = {"url": res.get("url", ""), "error": "submission failed"}
        return {"article_id": art.id, "ok": True, "event": "article.refreshed",
                "render_target": "blocks", "wp_post_id": int(post_id),
                "url": res.get("url", ""), "status": res.get("status", ""),
                "categories": list(post.categories), "tags": list(post.tags),
                "category_source": tax.get("category_source", ""),
                "indexing": indexing}
    finally:
        s.close()


def wp_post(post_id: int) -> dict:
    """Read a WordPress post back — raw content + registered SEO meta
    (Yoast/RankMath/AIOSEO) — for the refresh/decay path (verify an update,
    read before rewriting, or feed decay analysis). WordPress must be
    configured (WP_BASE_URL/WP_USERNAME/WP_APP_PASSWORD)."""
    from lib.wordpress import WPConfig, WordPressConnector

    cfg = WPConfig.from_env()
    if not (cfg.base_url and cfg.username and cfg.app_password):
        return _err("WordPress not configured",
                    "set WP_BASE_URL, WP_USERNAME, WP_APP_PASSWORD")
    try:
        return WordPressConnector(cfg).get_post(int(post_id))
    except Exception as exc:  # noqa: BLE001 — service never raises
        return _err(f"wp post read failed: {type(exc).__name__}: {exc}",
                    "check the post id, WP config, and site reachability")


def get_images(article_id: int) -> dict:
    data = get_article(article_id, include_content=True)
    if "error" in data:
        return data
    images = (data.get("meta") or {}).get("images", [])
    return {"images": images, "count": len(images)}


_IMAGE_MEDIA_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".webp": "image/webp", ".gif": "image/gif",
}


def get_article_image(article_id: int, name: str) -> dict:
    """Resolve one staged `meta.images` file for static serving (Wave 3).

    The article's own `meta.images` rows are the complete allowlist: `name`
    is matched against each row's basename, so a request can never reach a
    file the article doesn't reference (and path traversal is a non-starter).
    Remote-only rows (`url`, no local `path`) are not servable — the console
    renders those from their source URL directly."""
    init_db()
    s = get_session()
    try:
        art = s.get(ArticleModel, article_id)
        if art is None:
            return _err(f"article {article_id} not found", "run list_articles first")
        asked = str(name or "").strip()
        if (not asked or "/" in asked or "\\" in asked
                or os.path.basename(asked) != asked or asked in (".", "..")):
            return _err("invalid image name", "pass the file name only")
        rows = (art.meta or {}).get("images") or []
        for row in rows:
            if not isinstance(row, dict):
                continue
            p = str(row.get("path") or "")
            if not p or os.path.basename(p) != asked:
                continue
            if not os.path.isfile(p):
                return _err(f"image '{asked}' is no longer on disk",
                            "re-run stage-images to refresh meta.images")
            media_type = _IMAGE_MEDIA_TYPES.get(os.path.splitext(p)[1].lower())
            if media_type is None:
                return _err(f"'{asked}' is not a servable image type",
                            "jpg/png/webp/gif only")
            return {"path": p, "media_type": media_type,
                    "bytes": os.path.getsize(p)}
        return _err(f"image '{asked}' not found on article {article_id}",
                    "GET /articles/{id}/content for meta.images")
    finally:
        s.close()


CADENCE_INTERVALS: dict[str, timedelta | None] = {
    "manual": None,
    "daily": timedelta(days=1),
    "every_2_days": timedelta(days=2),
    "twice_a_week": timedelta(days=3, hours=12),
    "weekly": timedelta(days=7),
    "biweekly": timedelta(days=14),
    "monthly": timedelta(days=30),
}


def provision_site(slug: str, name: str = "", site_type: str = "custom", base_url: str = "",
                   settings: dict | None = None, key_label: str = "", key_scopes: list[str] | None = None,
                   rotate_key: bool = False, check_health: bool = True, via: str = "api") -> dict:
    """Onboard a site in ONE call (TEN-08): create/update the site, mint its scoped API key, and report whether
    it can reach its CMS - replacing ~21 manual steps across the console, the env and a redeploy.

    Idempotent and safe to re-run: the site is upserted (stored secrets survive a re-send, see
    `merge_settings`); a key is minted only if the site has none yet (or `rotate_key=True`), because the
    plaintext key exists exactly once. Returns `{site, key?, health?, next}` where `next` lists what is still
    left for a human (e.g. a WordPress app password was not supplied)."""
    slug = (slug or "").strip()
    if not valid_site_slug(slug):
        return _err(f"invalid site slug {slug!r}", "use lower-case letters, digits and hyphens (max 63 chars)")
    site_type = (site_type or "custom").strip().lower()
    if site_type not in ("custom", "wordpress"):
        return _err(f"invalid site_type {site_type!r}", "use 'custom' or 'wordpress'")
    base_url = (base_url or "").strip()
    if base_url and not base_url.startswith(("http://", "https://")):
        return _err("invalid base_url", "use a full URL such as https://example.com")

    site = upsert_site(slug, name=name, site_type=site_type, base_url=base_url, settings=settings or {})
    if "error" in site:
        return site

    from sdk import keys as site_keys
    existing = site_keys.list_site_keys(slug)
    active = [k for k in (existing.get("keys") or []) if not k.get("revoked")]
    out: dict[str, Any] = {"site": site, "created": bool(site.get("created"))}
    todo: list[str] = []
    if active and not rotate_key:
        out["key"] = None
        out["key_note"] = f"site already has {len(active)} active key(s); pass rotate_key=true to mint another"
    else:
        minted = site_keys.create_site_key(slug, label=key_label or "provisioned",
                                           scopes=key_scopes or ["read", "write"], via=via)
        if "error" in minted:
            return minted
        out["key"] = minted
        todo.append("store the API key now - it is shown only once")

    stored = (settings or {})
    if site_type == "wordpress":
        wp = stored.get("wp") if isinstance(stored.get("wp"), dict) else {}
        have_stored = bool(((get_site_settings_raw(slug) or {}).get("wp") or {}).get("app_password"))
        if not (wp.get("username") and (wp.get("app_password") or have_stored)):
            todo.append("add the WordPress username and application password (Settings > WordPress)")
    if not base_url and not site.get("base_url"):
        todo.append("set the site's public base URL (used for canonicals, internal links and IndexNow)")
    if check_health and (base_url or site.get("base_url")):
        try:
            out["health"] = site_health(slug)
        except Exception as exc:  # noqa: BLE001 - health is advisory
            out["health"] = {"error": f"{type(exc).__name__}: {exc}"}
    todo.append("optionally set cadence, quality and delivery/webhook settings, then submit the first article")
    out["next"] = todo
    s = get_session()
    try:
        row = _site_by_slug(s, slug)
        s.add(AuditLog(site_id=row.id if row else None, action="site.provision",
                       payload={"via": via, "site_type": site_type, "minted_key": bool(out.get("key")),
                                "created": out["created"]}))
        s.commit()
    finally:
        s.close()
    return out


def get_site_settings_raw(slug: str) -> dict | None:
    """The stored settings blob (unredacted) - for internal checks only, never returned from an API."""
    init_db()
    s = get_session()
    try:
        row = _site_by_slug(s, slug)
        return dict(row.settings or {}) if row else None
    finally:
        s.close()


def _int_setting(value: Any, *, default: int, lo: int, hi: int) -> int:
    """A numeric setting from `Site.settings` (a free-form JSON blob an operator or a client edits), as an int
    in [lo, hi]. A string like "abc", null or a nested object used to raise ValueError/TypeError inside
    `get_site_cadence_status`, which the console, publish and the scheduler all call - one bad value took the
    whole site's pages down (ENG-17)."""
    try:
        n = int(float(str(value).strip())) if value not in (None, "", False) else default
    except (TypeError, ValueError, OverflowError):
        return default
    return max(lo, min(hi, n))


def get_site_cadence_status(s, site: Site) -> dict:
    """Computes the current posting cadence status and next publication slot for a site."""
    settings = dict(site.settings or {})
    freq = str(settings.get("posting_frequency") or "daily")
    max_posts = _int_setting(settings.get("max_posts_per_cadence"), default=1, lo=1, hi=100)
    require_approval = bool(settings.get("require_approval", True))
    auto_publish = bool(settings.get("auto_publish", False))
    publish_mode = str(settings.get("publish_mode") or "draft")

    # Published posts, newest first. The window is the cadence interval: at most
    # `max_posts_per_cadence` posts may have gone out within the trailing interval.
    # (This used to look only at the time since the LAST post, so the cap was read,
    # reported, and never applied -- plan SEO-05.)
    rows = s.execute(
        select(Article)
        .where(Article.site_id == site.id, Article.status == "published")
        .order_by(Article.published_at.desc(), Article.created_at.desc())
        .limit(200)
    ).scalars().all()
    latest_pub = rows[0] if rows else None

    now = datetime.now(timezone.utc)
    interval = CADENCE_INTERVALS.get(freq, timedelta(days=1))

    def _aware(dt):
        return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt

    pub_times = sorted(t for t in (_aware(a.published_at or a.created_at) for a in rows) if t is not None)
    last_pub_dt = pub_times[-1] if pub_times else None
    in_window = [t for t in pub_times if interval is not None and now - t < interval]

    can_publish_now = True
    next_allowed_at = None
    seconds_remaining = 0

    if freq == "manual":
        can_auto_publish = False
    elif interval is not None:
        if len(in_window) >= max_posts:
            # The slot frees up when the oldest post that still counts ages out of the window.
            can_publish_now = False
            next_allowed_at = in_window[len(in_window) - max_posts] + interval
            seconds_remaining = max(0, int((next_allowed_at - now).total_seconds()))
        elif last_pub_dt is not None:
            next_allowed_at = last_pub_dt + interval   # informational: when the last post's window ends
        can_auto_publish = auto_publish and can_publish_now
    else:
        can_auto_publish = auto_publish

    return {
        "frequency": freq,
        "max_posts_per_cadence": max_posts,
        "require_approval": require_approval,
        "auto_publish": auto_publish,
        "publish_mode": publish_mode,
        "last_published_at": _iso(last_pub_dt) if last_pub_dt else None,
        "last_published_id": latest_pub.id if latest_pub else None,
        "last_published_title": latest_pub.title if latest_pub else None,
        "next_allowed_at": _iso(next_allowed_at) if next_allowed_at else None,
        "can_publish_now": can_publish_now,
        "seconds_remaining": seconds_remaining,
        "can_auto_publish": can_auto_publish,
        "posts_in_window": len(in_window),
        "enforced": bool(settings.get("enforce_cadence", False)),
    }


def site_cadence(site_slug: str) -> dict:
    """Direct query for site posting cadence status."""
    init_db()
    s = get_session()
    try:
        site = _site_by_slug(s, site_slug)
        if site is None:
            return _err(f"site '{site_slug}' not found", "run list_sites for valid slugs")
        return {"site": site.slug, "cadence": get_site_cadence_status(s, site)}
    finally:
        s.close()

def site_health(site_slug: str, *, http_get=None) -> dict:
    """§5.6 / pack technical-foundations pre-content gate.

    Beyond the ledger + WP config checks, probes the live site when it has a
    ``base_url`` (best-effort, 5s timeout each, injectable ``http_get`` for
    tests): crawlability (``robots.txt``), indexation (WP sitemap /
    engine-generated sitemap + WP search visibility ``blog_public``), and
    structure (llms.txt/sitemap availability). A blocked search-visibility
    flag is critical (flips ``ok``); robots/sitemap warnings stay advisory.
    """
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
        # Per-site credentials (plan SEC-08): reading WP_* from the process env here
        # meant a shared engine sent tenant A's application password to tenant B's
        # host, and reported the wrong tenant's config as "OK".
        wp_cfg = _wp_config(site)
        wp_ok = bool(wp_cfg.base_url and wp_cfg.username and wp_cfg.app_password)
        checks = [
            "keyword ledger: OK" if briefable > 0 else
            "keyword ledger: EMPTY queue — research/approve keywords (§5.16)",
            "WordPress config: OK" if wp_ok else
            "WordPress config: missing base URL / username / application password "
            "(site settings, or WP_* env on a single-site instance)",
        ]
        critical: list[str] = []
        base = (site.base_url or "").strip().rstrip("/")
        if base:
            get = http_get
            if get is None:
                import requests as _requests
                get = _requests.get
            # --- crawlability: robots.txt ---
            try:
                r = get(f"{base}/robots.txt", timeout=5)
                code = int(getattr(r, "status_code", 0) or 0)
                if code == 200:
                    checks.append("robots.txt: OK")
                elif code == 404:
                    checks.append("robots.txt: MISSING (crawl defaults apply — "
                                  "consider adding one)")
                else:
                    checks.append(f"robots.txt: unreachable (HTTP {code})")
            except Exception as exc:  # noqa: BLE001 — probe never raises
                checks.append(f"robots.txt: unreachable ({type(exc).__name__})")
            # --- indexation: sitemap ---
            if (site.site_type or "") == "wordpress":
                try:
                    r = get(f"{base}/wp-sitemap.xml", timeout=5)
                    code = int(getattr(r, "status_code", 0) or 0)
                    if code == 200:
                        checks.append("sitemap (wp-sitemap.xml): OK")
                    else:
                        checks.append(f"sitemap (wp-sitemap.xml): HTTP {code} — "
                                      "enable WP core sitemaps (WP ≥ 5.5)")
                except Exception as exc:  # noqa: BLE001
                    checks.append(f"sitemap (wp-sitemap.xml): unreachable "
                                  f"({type(exc).__name__})")
            else:
                checks.append(
                    f"sitemap: engine-generated for {published} published page(s) "
                    f"at /sdk/v1/sites/{site.slug}/sitemap.xml — serve it at "
                    "{base}/sitemap.xml")
            # --- indexation: WP search visibility (critical) ---
            if (site.site_type or "") == "wordpress" and wp_ok:
                try:
                    r = get(f"{base}/wp-json/wp/v2/settings", timeout=5,
                            auth=(wp_cfg.username, wp_cfg.app_password))
                    code = int(getattr(r, "status_code", 0) or 0)
                    if code == 200:
                        visible = (r.json() or {}).get("blog_public")
                        if visible == 1:
                            checks.append("WP search visibility: OK "
                                          "(blog_public=1, indexing allowed)")
                        else:
                            msg = ("WP search visibility: BLOCKED (blog_public=0 — "
                                   "site discourages search engines; fix in "
                                   "WP Settings → Reading)")
                            checks.append(msg)
                            critical.append(msg)
                    else:
                        checks.append(f"WP search visibility: unknown (HTTP {code})")
                except Exception as exc:  # noqa: BLE001
                    checks.append(f"WP search visibility: unknown "
                                  f"({type(exc).__name__})")
        else:
            checks.append("site base_url: not set — live probes "
                          "(robots/sitemap/visibility) skipped")
        cadence = get_site_cadence_status(s, site)
        return {"site": site.slug, "ok": briefable > 0 and not critical,
                "ledger": {"briefable": briefable, "published": published},
                "wp_configured": wp_ok, "base_url": base,
                "checks": checks, "critical": critical,
                "cadence": cadence}
    finally:
        s.close()


def sitemap_xml(site_slug: str) -> dict:
    """§5.6 XML sitemap maintained per site — published articles, newest first.

    Returns JSON {"site", "count", "sitemap_xml"} (same shape as llms_txt);
    the site serves the text at {base}/sitemap.xml. WordPress sites use their
    core sitemap instead — this is the custom-site path.
    """
    init_db()
    s = get_session()
    try:
        site = _site_by_slug(s, site_slug)
        if site is None:
            return _err(f"site '{site_slug}' not found", "run list_sites for valid slugs")
        from lib.geo import sitemap_xml as _sitemap_xml

        base = (site.base_url or "").rstrip("/")
        rows = s.execute(
            select(Article).where(Article.site_id == site.id,
                                  Article.status == "published")
            .order_by(Article.published_at.desc())
        ).scalars().all()
        entries = []
        for a in rows:
            slug = _resolve_slug(a)
            if not slug or slug == "untitled":
                continue
            dt = a.published_at or a.created_at
            entries.append({"loc": f"{base}/{slug}" if base else slug,
                            "lastmod": dt.strftime("%Y-%m-%d") if dt else ""})
        return {"site": site.slug, "count": len(entries),
                "sitemap_xml": _sitemap_xml(entries)}
    finally:
        s.close()


def llms_txt(site_slug: str) -> dict:
    """Generate the site's `llms.txt` (§5.8 GEO) from its PUBLISHED articles —
    the agent-facing index a custom site serves at `/llms.txt`.

    Companion to the per-article `markdown_alternate` (the `.md` alternate):
    the site owns the URL, the engine composes the content.
    """
    from lib.geo import generate_llms_txt

    init_db()
    s = get_session()
    try:
        site = _site_by_slug(s, site_slug)
        if site is None:
            return _err(f"site '{site_slug}' not found", "run list_sites for valid slugs")
        site_name = site.name or site.slug
        base = (site.base_url or "").rstrip("/")
        listings = list_articles(site_slug=site.slug, status="published", limit=500)
        pages = []
        for a in listings.get("articles", []):
            slug = a.get("slug") or a.get("title") or ""
            pages.append({
                "title": a.get("title", ""),
                "url": f"{base}/{slug}" if base else slug,
            })
        text = generate_llms_txt(site_name, base or site.slug, pages)
        return {"site": site.slug, "count": len(pages), "llms_txt": text}
    finally:
        s.close()


# --- Elementor render target (native REST, §5.11/§5.13) ----------------
# Elementor >= 3.27 exposes document meta over show_in_rest, so these ops
# ride the same WP application-password connection — no MCP dependency.


def _elementor_client():
    """ElementorClient bound to WPConfig.from_env(). Raises when unconfigured
    (callers wrap into _err)."""
    from lib.elementor import ElementorClient
    from lib.wordpress import WPConfig
    cfg = WPConfig.from_env()
    if not (cfg.base_url and cfg.username and cfg.app_password):
        raise ValueError(
            "WordPress not configured — set WP_BASE_URL, WP_USERNAME, WP_APP_PASSWORD")
    return ElementorClient(cfg)


def _check_post_type(post_type: str) -> dict | None:
    if post_type not in ("posts", "pages"):
        return _err(f"invalid post_type '{post_type}'",
                    "use 'posts' (default) or 'pages' — the whitelist prevents path injection")
    return None


def elementor_available() -> dict:
    """Preflight: does the site expose _elementor_data over REST? (OPTIONS probe)"""
    try:
        return _elementor_client().available()
    except Exception as exc:  # noqa: BLE001 — service never raises
        return _err(f"elementor probe failed: {type(exc).__name__}: {exc}",
                    "set WP_BASE_URL/WP_USERNAME/WP_APP_PASSWORD (Administrator app "
                    "password) and confirm Elementor >= 3.27 is active")


def elementor_document(post_id: int, post_type: str = "posts") -> dict:
    """Read the current Elementor document (root elements + page settings)."""
    bad = _check_post_type(post_type)
    if bad:
        return bad
    try:
        return _elementor_client().get_document(post_id, post_type=post_type)
    except Exception as exc:  # noqa: BLE001
        return _err(f"elementor document read failed: {type(exc).__name__}: {exc}",
                    "check the post id and that Elementor >= 3.27 is active on the site")


def elementor_save(post_id: int, elements: list, post_type: str = "posts",
                   page_settings: dict | None = None) -> dict:
    """Replace a post's Elementor document (full-document write). Audited."""
    bad = _check_post_type(post_type)
    if bad:
        return bad
    if not isinstance(elements, list) or not elements:
        return _err("elements must be a non-empty array of root element objects",
                    'fetch GET /sdk/v1/elementor/posts/{post_id} for the current shape, '
                    'or pass [{"id","elType","settings","elements"}]')
    try:
        result = _elementor_client().save_document(
            post_id, elements, post_type=post_type, page_settings=page_settings)
    except Exception as exc:  # noqa: BLE001
        return _err(f"elementor save failed: {type(exc).__name__}: {exc}",
                    "confirm the post exists, Elementor >= 3.27 is active, and the "
                    "app password belongs to an Administrator")
    init_db()
    s = get_session()
    try:
        s.add(AuditLog(action="elementor.save",
                       payload={"post_id": post_id, "post_type": post_type,
                                "elements": len(elements)}))
        s.commit()
    finally:
        s.close()
    result["post_id"] = post_id
    return result


def elementor_build(article_id: int, post_id: int | None = None,
                    mode: str = "draft") -> dict:
    """Compose the article as an Elementor document (§5.11 elementor target).

    - post_id or meta.wp_post_id present → save the layout onto that post.
    - otherwise → create the WP post first with plain-HTML fallback content
      (render_target="elementor"; publish() writes the Elementor doc right
      after creation, fail-open), store meta.wp_post_id, audit.

    meta.wp_post_id is always reused → builds never duplicate posts.
    Local imports keep WordPressConnector/ElementorClient patchable in tests.
    """
    mode = "auto" if str(mode).strip().lower() in ("publish", "live") else mode  # same meaning (plan ENG-02)
    if mode not in ("draft", "auto"):
        return _err(f"invalid mode '{mode}'", "use 'draft' (default) or 'auto' (alias: 'publish')")
    init_db()
    s = get_session()
    try:
        art = s.get(ArticleModel, article_id)
        if art is None:
            return _err(f"article {article_id} not found", "run generate_article first")
        if not (art.content_md or "").strip():
            return _err(f"article {article_id} has no content yet",
                        "run the content stage first (content_md is empty)")

        from lib.elementor import ElementorClient, build_blog_page_data
        from lib import wp_render
        from lib.wordpress import WPConfig, WordPressConnector, build_prepared_post

        # copy BEFORE mutating — in-place JSON mutation defeats SQLAlchemy
        # change tracking when the same object is reassigned
        meta = dict(art.meta) if isinstance(art.meta, dict) else {}
        brief = meta.get("brief") if isinstance(meta.get("brief"), dict) else {}
        if post_id is None and meta.get("wp_post_id"):
            post_id = int(meta["wp_post_id"])

        cfg = _wp_config(art.site)
        if not (cfg.base_url and cfg.username and cfg.app_password):
            return _err("WordPress not configured",
                        "set WP_BASE_URL, WP_USERNAME, WP_APP_PASSWORD")

        slug = _resolve_slug(art)
        base = ((art.site.base_url if art.site else "") or "").strip().rstrip("/")
        url = f"{base}/{slug}" if base else ""
        post = build_prepared_post(
            title=art.title or slug,
            markdown=art.content_md,
            url=url,
            faqs=_parse_faqs(meta.get("faqs") or brief.get("faqs")),
            meta_description=str(brief.get("description") or meta.get("summary") or ""),
            slug=slug,
            cta=brief.get("cta") if isinstance(brief.get("cta"), dict) else None,
            entities=brief.get("entities") if isinstance(brief.get("entities"), list) else None,
            date_published=_iso(art.published_at or art.created_at),
            date_modified=_modified_iso(art),
            schema_extra=_schema_extra(art, meta, brief),
            focus_keyphrase=_focus_keyphrase(meta, brief),
            render_target="elementor",
        )

        if post_id is None:
            try:
                result = WordPressConnector(cfg).publish(post, mode=mode)
            except Exception as exc:  # noqa: BLE001
                return _err(f"wp publish failed: {type(exc).__name__}: {exc}",
                            "check WP config, outbound links (pre_publish_checks), "
                            "and site reachability")
            elementor_state = result.get("elementor") or {
                "ok": False, "error": "publish did not report an elementor write"}
            meta["wp_post_id"] = result["id"]
            meta["render_target"] = "elementor"     # refresh_article must rewrite _elementor_data too (ADP-09)
            art.meta = meta
            s.add(AuditLog(article_id=art.id, site_id=art.site_id,
                           action="article.elementor_build",
                           payload={"wp_post_id": result["id"], "mode": mode,
                                    "elementor": elementor_state}))
            s.commit()
            return {"article_id": art.id, "wp_post_id": result["id"],
                    "url": result.get("url", ""), "status": result.get("status", ""),
                    "render_target": "elementor", "elementor": elementor_state}

        # existing post: compose the body + save the document directly
        # (FAQ accordion widget comes from post.faqs, not the body HTML)
        body = post.html + "\n" + wp_render.jsonld_script(post.article_schema)
        if post.faq_schema:
            body += "\n" + wp_render.jsonld_script(post.faq_schema)
        try:
            res = ElementorClient(cfg).save_document(
                post_id, build_blog_page_data(post.title, body, faqs=post.faqs),
                page_settings={"hide_title": "yes"})
        except Exception as exc:  # noqa: BLE001
            return _err(f"elementor save failed: {type(exc).__name__}: {exc}",
                        "confirm the post id, Elementor >= 3.27, and an "
                        "Administrator app password")
        meta["wp_post_id"] = post_id
        meta["render_target"] = "elementor"
        art.meta = meta
        s.add(AuditLog(article_id=art.id, site_id=art.site_id,
                       action="article.elementor_build",
                       payload={"wp_post_id": post_id, "mode": mode, "elementor": res}))
        s.commit()
        return {"article_id": art.id, "wp_post_id": post_id, "url": res.get("url", ""),
                "render_target": "elementor", "elementor": res}
    finally:
        s.close()
