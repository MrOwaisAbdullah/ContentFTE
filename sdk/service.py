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
    if mode not in ("draft", "auto"):
        return _err(f"invalid mode '{mode}'", "use 'draft' (default) or 'auto'")
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

        cfg = WPConfig.from_env()
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
            date_published=_iso(art.created_at),
            date_modified=_iso(art.published_at or art.created_at),
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
        body = post.html + "\n" + wp_render.jsonld_script(post.article_schema)
        if post.faq_schema:
            body += "\n" + wp_render.jsonld_script(post.faq_schema)
        try:
            res = ElementorClient(cfg).save_document(
                post_id, build_blog_page_data(post.title, body),
                page_settings={"hide_title": "yes"})
        except Exception as exc:  # noqa: BLE001
            return _err(f"elementor save failed: {type(exc).__name__}: {exc}",
                        "confirm the post id, Elementor >= 3.27, and an "
                        "Administrator app password")
        meta["wp_post_id"] = post_id
        art.meta = meta
        s.add(AuditLog(article_id=art.id, site_id=art.site_id,
                       action="article.elementor_build",
                       payload={"wp_post_id": post_id, "mode": mode, "elementor": res}))
        s.commit()
        return {"article_id": art.id, "wp_post_id": post_id, "url": res.get("url", ""),
                "render_target": "elementor", "elementor": res}
    finally:
        s.close()
