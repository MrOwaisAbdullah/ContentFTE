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

import json
import os
import re
import shutil
import tempfile
import time
from datetime import datetime, timezone
from typing import Any

from slugify import slugify
from sqlalchemy import func, select

from lib import custom_site
from lib import generation
from lib.db import Article, Article as ArticleModel, AuditLog, KeywordLedger, Site, get_session, init_db
from lib.cost_ledger import finalize, record_cost, usage_cost
from lib.ledger import INTENT_VALUE, briefable_rows, set_status, upsert_keyword
from lib.taxonomy import derive_taxonomy


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


def list_articles(site_slug: str = "", status: str = "", limit: int = 100,
                  offset: int = 0) -> dict:
    """List articles newest-first, optionally scoped to a site and/or status.

    Powers the custom-site **content loader** (§5.12 pull): enumerate a site's
    published articles, then fetch each one's `/content` payload by id. Only
    routing fields are returned (no html/markdown) — cheap to page through.
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
        total = int(s.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
        rows = s.execute(
            stmt.order_by(Article.created_at.desc(), Article.id.desc())
                .limit(limit).offset(offset)
        ).scalars().all()
        slug_by_id: dict[int, str] = ({scoped_site.id: scoped_site.slug}
                                      if scoped_site else {})
        articles: list[dict] = []
        for a in rows:
            if a.site_id not in slug_by_id:
                row = s.get(Site, a.site_id)
                slug_by_id[a.site_id] = row.slug if row else ""
            articles.append({
                "id": a.id, "site_id": a.site_id, "site_slug": slug_by_id[a.site_id],
                "title": a.title, "slug": _resolve_slug(a), "status": a.status,
                "created_at": _iso(a.created_at), "published_at": _iso(a.published_at),
                "cost_usd": a.cost_usd,
            })
        return {"articles": articles, "count": len(articles), "total": total,
                "limit": limit, "offset": offset}
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


def _content_checks(*, content: str, title: str, summary: str,
                    faqs: list | None, brief: dict) -> dict:
    """Deterministic draft gate — every check is {pass, value, need}.

    Checks whose inputs are absent (no link candidates, no sources) pass
    fail-open so a sparse brief never dead-locks generation; only provable
    failures report. `GEN_MIN_WORDS` (default 900) is the hard word floor."""
    words = len((content or "").split())
    min_words = int(os.environ.get("GEN_MIN_WORDS") or "900")
    md_links = re.findall(r"\[[^\]]*\]\(([^)\s]+)\)", content or "")
    site_base = str(brief.get("site_base_url") or "").rstrip("/")
    internal = [l for l in md_links if site_base and l.startswith(site_base)]
    external = [l for l in md_links
                if l.startswith(("http://", "https://"))
                and not (site_base and l.startswith(site_base))]
    stale_re = re.compile(r"\bin\s+20(?:1\d|2[0-5])\b", re.I)
    checks: dict[str, dict] = {
        "words": {"pass": words >= min_words, "value": words, "need": min_words},
        "tldr": {"pass": bool(re.search(r"TL\s*;?\s*DR", (content or "")[:800], re.I))},
        "sources": {"pass": bool(re.search(r"^##[ \t]+Sources\b", content or "", re.M | re.I))},
        "faqs": {"pass": len(faqs or []) >= 3, "value": len(faqs or []), "need": 3},
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


def _enrich_brief_with_links(art: ArticleModel, brief: dict, keyword: str) -> dict:
    """Embed REAL internal-link candidates into the generation brief.

    The generator's own link tools only know the Sanity site; WordPress
    articles need candidates from the target WP itself. Production-only
    (site_type=wordpress + WP_* env) — CI/tests never satisfy both, so no
    network in tests. Fail-open: any problem means the brief stays as-is."""
    if (getattr(art.site, "site_type", "") or "") != "wordpress":
        return brief
    try:
        from lib.wordpress import WPConfig, WordPressConnector

        cfg = WPConfig.from_env()
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


async def _default_generate(brief: dict) -> str:
    """Production generation seam: lazily runs content_generator_agent
    (heavy agents stack loads only on first generation). Tests and the MCP
    end-to-end smoke monkeypatch this — never hit the network in CI."""
    from blog_agent.generation import generate_with_agent

    return await generate_with_agent(brief)


async def generate_content(article_id: int, *, generate_fn=None,
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
            feedback = [f"{name}: {json.dumps(val)}"
                        for name, val in checks.items() if not val.get("pass")]
            brief = dict(brief)
            brief["revision_feedback"] = feedback

        gen_wall_s = round(time.time() - gen_started, 1)
        if parsed is None:
            return _err("agent returned no usable content",
                        "retry generate_content")
        previous_title = art.title
        quality = generation.parse_score(generation.get_field(parsed, "Quality Score"))
        warnings = generation.get_field(parsed, "warnings") or []
        errors = generation.get_field(parsed, "errors") or []
        claims_notes = str(generation.get_field(parsed, "Claims Notes") or "").strip()

        # Mechanical stale-year fix in the title only ("in 2025" -> current
        # year): safe because the pattern is explicit; body years are left to
        # the model instructions + the revise feedback above.
        stale_title = re.search(r"\bin\s+20(?:1\d|2[0-5])\b", title or "", re.I)
        if stale_title:
            year = datetime.now(timezone.utc).year
            title = re.sub(r"\bin\s+20(?:1\d|2[0-5])\b", f"in {year}",
                           title, flags=re.I)
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
            art.scores = {**(art.scores or {}), "overall": quality}

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
        data: dict[str, Any] = {"id": art.id, "site_id": art.site_id, "title": art.title,
                                "slug": _resolve_slug(art), "status": art.status,
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

        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        suffix = image_format.sniff_ext(resp.content, fallback=".jpg")
        with NamedTemporaryFile(delete=False, suffix=suffix) as fh:
            fh.write(resp.content)
            return fh.name
    except Exception:  # noqa: BLE001 — an unusable source skips the image
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

    cfg = WPConfig.from_env()
    if not (cfg.base_url and cfg.username and cfg.app_password):
        return {"ok": False, "error": "WordPress not configured",
                "next": "set WP_BASE_URL, WP_USERNAME, WP_APP_PASSWORD"}
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
            date_published=_iso(art.created_at),
            date_modified=_iso(art.published_at or art.created_at),
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


def publish_article(article_id: int, mode: str = "draft", via: str = "api") -> dict:
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
        if art.status not in ("approved", "published"):
            return _err(
                f"article {article_id} is '{art.status}' — publish requires 'approved'",
                "gate: overall >=90 and every sub-score >=80, then POST /sdk/v1/articles/{id}/approve")
        art.status = "published"
        # §5.10-6 finalize the per-post cost ledger at publish.
        totals = finalize(s, art.id)
        art.cost_usd = totals["total_usd"]

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
        return out
    finally:
        s.close()


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

        cfg = WPConfig.from_env()
        if not (cfg.base_url and cfg.username and cfg.app_password):
            return _err("WordPress not configured",
                        "set WP_BASE_URL, WP_USERNAME, WP_APP_PASSWORD")
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
                date_published=_iso(art.created_at),
                date_modified=_iso(datetime.now(timezone.utc)),
                focus_keyphrase=_focus_keyphrase(meta, brief),
                render_target="blocks",
            )
            body = _render_wp_body(conn, post)
            res = conn.update_post(int(post_id), post, body_html=body,
                                   featured_image_path=featured_path)
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
        return {"article_id": art.id, "ok": True, "event": "article.refreshed",
                "render_target": "blocks", "wp_post_id": int(post_id),
                "url": res.get("url", ""), "status": res.get("status", ""),
                "categories": list(post.categories), "tags": list(post.tags),
                "category_source": tax.get("category_source", "")}
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
        art.meta = meta
        s.add(AuditLog(article_id=art.id, site_id=art.site_id,
                       action="article.elementor_build",
                       payload={"wp_post_id": post_id, "mode": mode, "elementor": res}))
        s.commit()
        return {"article_id": art.id, "wp_post_id": post_id, "url": res.get("url", ""),
                "render_target": "elementor", "elementor": res}
    finally:
        s.close()
