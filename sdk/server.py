"""§5.12 Custom-site SDK — REST routes (FastAPI APIRouter).

Thin HTTP layer over `sdk/service.py` (the canonical operations). MCP tools
consume the same service, so API and MCP behavior cannot drift.

Endpoints:
    POST /sdk/v1/articles                 -> submit brief/keyword
    GET  /sdk/v1/articles                 -> list articles (site_slug, status, limit, offset)
    GET  /sdk/v1/articles/{id}            -> status, scores, cost
    POST /sdk/v1/articles/{id}/generate   -> run real generation (briefed -> drafted)
    POST /sdk/v1/articles/{id}/approve    -> approve / needs_review
    POST /sdk/v1/articles/{id}/publish    -> mark published (approved only);
                                             site_type="wordpress" sites are
                                             pushed to WP in the same call
                                             ({"wp": {...}} in the response)
    POST /sdk/v1/articles/{id}/refresh    -> update an existing WP post in place
                                             (decay path; custom sites re-pull)
    GET  /sdk/v1/articles/{id}/content    -> unified delivery payload
                                              (html + markdown + meta + JSON-LD)
    GET  /sdk/v1/articles/{id}/images/{name} -> static-serve one staged
                                              meta.images file (row-name allowlist)
    GET  /sdk/v1/sites                    -> list sites
    POST /sdk/v1/sites                    -> create / update a site
    GET  /sdk/v1/sites/{slug}/health      -> site health
    GET  /sdk/v1/sites/{slug}/queue       -> keyword-ledger view (console; parity §B1)
    GET  /sdk/v1/sites/{slug}/brief       -> next briefable keyword (read-only peek)
    GET  /sdk/v1/sites/{slug}/research    -> research_data worksheet view (console)
    GET  /sdk/v1/sites/{slug}/briefs      -> content_briefs worksheet view (console)
    GET  /sdk/v1/logs                     -> audit + cost ledger view,
                                             limit/offset paged (console)
    PATCH /sdk/v1/articles/{id}/content   -> operator edit of content_md (console)
    POST /sdk/v1/run/{stage}              -> trigger a pipeline stage in the
                                              background (console; 409 on overlap)
    GET  /sdk/v1/stages                   -> stage history (stage.run audit rows)
                                              + live running set (console)
    GET  /sdk/v1/sites/{slug}/llms.txt    -> site llms.txt (§5.8 GEO) from published articles
    GET  /sdk/v1/wp/posts/{id}            -> read a WP post back (raw content + SEO meta)
    GET  /sdk/v1/elementor/available      -> Elementor REST meta probe (status body)
    GET  /sdk/v1/elementor/posts/{id}     -> current Elementor document (elements)
    POST /sdk/v1/elementor/posts/{id}     -> replace the document (elements, page_settings)
    POST /sdk/v1/elementor/articles/{id}/build -> compose article as Elementor doc

Auth: per-site API key via X-Site-Key header (SDK_MASTER_KEY, dev-open when
unset). Idempotency-Key honored on POST /articles (24h in-memory cache, bounded; see sdk/idempotency.py).
Webhook events returned in responses: article.ready / article.drafted /
article.approved (legacy: article.published) / article.needs_review. Every mutating action is
audit-logged by the service.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import sdk.keys as site_keys
from sdk.errors import EngineHTTPError
import sdk.service as service
from sdk.auth import AuthContext, authenticate, current
from sdk.authz import authorize
from sdk.idempotency import IdempotencyCache

# `authorize` runs before every handler: it authenticates the key and, for site-scoped keys, enforces
# the route table in sdk/authz.py (unlisted routes are refused to site keys).
router = APIRouter(prefix="/sdk/v1", tags=["sdk"], dependencies=[Depends(authorize)])

logger = logging.getLogger("sdk.server")

_idempotency = IdempotencyCache(shared=True)


def _ctx() -> AuthContext:
    """Who is calling, as resolved by the router-level `authorize` dependency."""
    ctx = current()
    if ctx is None:  # defensive: handler reached without the router dependency
        raise HTTPException(status_code=500, detail="auth context missing")
    return ctx


def _check_site_key(x_site_key: str | None) -> str:
    """Kept so every handler still reads as "authenticated first". The real work happens once, in
    the router dependency (`sdk.authz.authorize`); this returns that result's label. Falls back to
    authenticating directly if the dependency somehow did not run."""
    ctx = current() or authenticate(x_site_key)
    return ctx.label


# Service error dicts may carry a machine-readable `code`; map it to the right HTTP status instead of
# the generic 404 (the article exists -- it's the request that can't be honoured).
_CODE_STATUS = {"budget_exceeded": 402, "gate_failed": 409,
                "publish_in_progress": 409, "generation_in_progress": 409}


def _resolve(data: dict) -> dict:
    """Service error dicts become HTTP errors; success passes through."""
    if "error" in data:
        raise EngineHTTPError(data)
    return data


class ArticleSubmit(BaseModel):
    site_slug: str
    keyword: str | None = None
    brief: dict[str, Any] = {}
    instant: bool = False


class ArticleApprove(BaseModel):
    approved: bool = True
    note: str = ""
    # Override a failed quality gate. Audited; use only after reading the reasons.
    force: bool = False


class ArticleGenerate(BaseModel):
    regenerate: bool = False  # true = rewrite an article that already has content


class ArticlePublish(BaseModel):
    mode: str = "draft"  # draft (default for new sites) | publish
    force: bool = False
    enforce_cadence: bool = False


class SiteUpsert(BaseModel):
    slug: str
    name: str = ""
    site_type: str = ""  # custom | wordpress; empty = keep existing (create defaults to custom)
    base_url: str = ""
    settings: dict[str, Any] | None = None


class ContentPatch(BaseModel):
    content_md: str
    note: str = ""


class StageRunRequest(BaseModel):
    site_slug: str | None = None


class ElementorSave(BaseModel):
    elements: list[dict[str, Any]]
    page_settings: dict[str, Any] | None = None
    post_type: str = "posts"  # posts | pages (whitelisted in the service)


class ElementorBuild(BaseModel):
    post_id: int | None = None  # omit → create (or reuse meta.wp_post_id)
    mode: str = "draft"  # draft (default) | auto


@router.post("/articles")
def submit_article(
    body: ArticleSubmit,
    background_tasks: BackgroundTasks,
    x_site_key: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None),
) -> dict:
    site_key = _check_site_key(x_site_key)
    # A site key may only submit to its own site (naming another is a 403; omitting means "mine").
    site_slug = _ctx().scoped_site(body.site_slug)
    body_hash = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    cache_key = None
    if idempotency_key:
        # Includes the site: two clients can pick the same label and Idempotency-Key.
        cache_key = hashlib.sha256(
            f"{site_key}:{site_slug}:{idempotency_key}:{body_hash}".encode()).hexdigest()
        replay = _idempotency.get(cache_key)
        if replay is not None:
            return replay
    result = service.submit_article(site_slug, keyword=body.keyword or "", brief=body.brief,
                                    create_site=service._may_autocreate_site(site_slug))
    if "error" in result:
        raise EngineHTTPError(result, 400)
    if body.instant and "id" in result:
        art_id = result["id"]
        background_tasks.add_task(service.run_instant_pipeline, art_id)
        result["instant_triggered"] = True
    if cache_key:
        _idempotency.set(cache_key, result)
    return result


@router.get("/articles/stats")
def article_stats(site_slug: str = "", since_days: int = 30,
                  x_site_key: str | None = Header(default=None)) -> dict:
    """Aggregated real (engine-backed) stats for the console (Overview,
    Sites, Insights): counts by status, quality aggregates, word totals,
    spend totals, and a per-day created series for the velocity chart.
    """
    _check_site_key(x_site_key)
    site_slug = _ctx().scoped_site(site_slug)
    return _resolve(service.article_stats(site_slug=site_slug,
                                          since_days=since_days))


@router.get("/articles")
def list_articles(site_slug: str = "", status: str = "", limit: int = 100,
                  offset: int = 0, q: str = "", sort: str = "created_at",
                  order: str = "desc", has_images: bool = False,
                  x_site_key: str | None = Header(default=None)) -> dict:
    """List articles newest-first, optionally scoped to a site and/or status.

    Powers the custom-site content loader: enumerate a site's published
    articles, then GET /articles/{id}/content for each.
    """
    _check_site_key(x_site_key)
    site_slug = _ctx().scoped_site(site_slug)
    return _resolve(service.list_articles(site_slug=site_slug, status=status,
                                          limit=limit, offset=offset, q=q,
                                          sort=sort, order=order,
                                          has_images=has_images))


@router.get("/articles/{article_id}")
def get_article(article_id: int, x_site_key: str | None = Header(default=None)) -> dict:
    _check_site_key(x_site_key)
    return _resolve(service.get_article(article_id))


@router.post("/articles/{article_id}/generate")
async def generate_article(article_id: int, body: ArticleGenerate | None = None,
                           x_site_key: str | None = Header(default=None)) -> dict:
    """Run real generation for a submitted article (briefed -> drafted, §5.5).
    Long-running (LLM, typically 30-120s) — idempotent: articles that
    already have content return as-is unless regenerate=true."""
    _check_site_key(x_site_key)
    result = await service.generate_content(
        article_id, regenerate=bool(body and body.regenerate))
    if "error" in result:
        if result.get("code") in _CODE_STATUS:
            raise EngineHTTPError(result)
        if "not found" in result["error"]:
            raise EngineHTTPError(result, 404)
        if result["error"].startswith(("generation failed", "agent returned",
                                       "generated content")):
            raise EngineHTTPError(result, 502)
        raise EngineHTTPError(result, 400)
    return result


@router.post("/articles/{article_id}/approve")
def approve_article(article_id: int, body: ArticleApprove,
                    x_site_key: str | None = Header(default=None)) -> dict:
    _check_site_key(x_site_key)
    result = service.approve_article(article_id, approved=body.approved,
                                     note=body.note, via="sdk", force=body.force)
    if result.get("code") == "gate_failed":
        # 409, not the generic 404 _resolve() would give: the article exists, its state
        # just doesn't pass. The reasons are in `detail` so any client can show them.
        raise EngineHTTPError(result, 409)
    return _resolve(result)


@router.get("/articles/{article_id}/gate")
def article_gate(article_id: int, check_links: bool | None = None,
                 x_site_key: str | None = Header(default=None)) -> dict:
    """Run the deterministic quality gate without approving (read-only): blocking failures,
    warnings and per-gate detail. `check_links=true` also HEADs every external link."""
    _check_site_key(x_site_key)
    return _resolve(service.check_article_gate(article_id, check_links=check_links))


@router.post("/articles/{article_id}/publish")
def publish_article(article_id: int, body: ArticlePublish | None = None,
                    x_site_key: str | None = Header(default=None)) -> dict:
    _check_site_key(x_site_key)
    result = service.publish_article(article_id,
                                     mode=(body.mode if body else "draft"),
                                     via="sdk",
                                     force=(body.force if body else False),
                                     enforce_cadence=(body.enforce_cadence if body else False))
    if "error" in result:
        err_msg = str(result["error"])
        if "cadence limit reached" in err_msg.lower():
            raise EngineHTTPError(result, 429)
        if "requires 'approved'" in err_msg or result.get("code") == "publish_in_progress":
            raise EngineHTTPError(result, 409)
        raise EngineHTTPError(result, 404)
    return result


@router.post("/articles/{article_id}/refresh")
def refresh_article(article_id: int, x_site_key: str | None = Header(default=None)) -> dict:
    """Refresh an already-published article on its site (§5.11 decay path).

    WordPress: updates the existing post in place (content + SEO meta +
    taxonomy) — never creates, never un-publishes. Custom sites: no push —
    re-pull GET /articles/{id}/content.
    """
    _check_site_key(x_site_key)
    return _resolve(service.refresh_article(article_id, via="sdk"))


@router.post("/articles/{article_id}/stage-images")
def stage_images(article_id: int, x_site_key: str | None = Header(default=None)) -> dict:
    """Stage featured/in-post images into meta.images (§5.9).

    Publish does this automatically when the article has no images yet;
    this route exists for pre-approval visibility and retries. No provider
    credentials (CLOUDFLARE_API_TOKEN / PEXELS_API_KEY) -> clean skip.
    """
    _check_site_key(x_site_key)
    return _resolve(service.stage_images(article_id))


@router.post("/articles/{article_id}/images/{name}/regenerate")
def regenerate_article_image(article_id: int, name: str,
                             x_site_key: str | None = Header(default=None)) -> dict:
    """Regenerate one staged meta.images row (featured / inpost).

    Re-runs the AI image generation for that slot and replaces the row in
    ``meta.images`` in-place. Cost and QA are overwritten from the new result.
    Best-effort: if no provider credentials, returns ``skipped``; any error
    returns ``{"error", "next"}`` without raising — the caller should surface
    the user a confirm dialog (spends credits) and a cost surface.

    The *name* must match the allowlisted row's ``path`` basename (same rule as
    ``GET /articles/{id}/images/{name}``) so a request can never reach an image
    the article doesn't reference.

    Returns:
        dict: {"id", "event": "article.images", "images", "featured", "inpost",
        "errors"?, "detail"} or {"error", "next"}.
    """
    _check_site_key(x_site_key)
    return _resolve(service.regenerate_article_image(article_id, name))


@router.get("/articles/{article_id}/content")
def get_content(article_id: int, x_site_key: str | None = Header(default=None)) -> dict:
    _check_site_key(x_site_key)
    return _resolve(service.get_article(article_id, include_content=True))


@router.get("/articles/{article_id}/images/{name}")
def get_article_image(article_id: int, name: str,
                      x_site_key: str | None = Header(default=None)) -> FileResponse:
    """Static-serve one staged meta.images file (console Media gallery).

    Allowlisted by the article's own meta.images rows; the console proxies
    these bytes to the browser so the page never needs the X-Site-Key."""
    _check_site_key(x_site_key)
    result = service.get_article_image(article_id, name)
    if "error" in result:
        raise EngineHTTPError(result, 404)
    return FileResponse(result["path"], media_type=result["media_type"],
                        headers={"Cache-Control": "private, max-age=60"})


@router.delete("/articles/{article_id}")
def delete_article(article_id: int, x_site_key: str | None = Header(default=None)) -> dict:
    _check_site_key(x_site_key)
    return _resolve(service.delete_article(article_id))


@router.delete("/keywords/{keyword_id}")
def delete_keyword(keyword_id: int, x_site_key: str | None = Header(default=None)) -> dict:
    _check_site_key(x_site_key)
    return _resolve(service.delete_keyword(keyword_id))


@router.post("/keywords/{keyword_id}/prioritize")
def prioritize_keyword(keyword_id: int, x_site_key: str | None = Header(default=None)) -> dict:
    _check_site_key(x_site_key)
    return _resolve(service.prioritize_keyword(keyword_id))


@router.get("/sites")
def list_sites(x_site_key: str | None = Header(default=None)) -> dict:
    _check_site_key(x_site_key)
    result = service.list_sites()
    ctx = _ctx()
    if not ctx.is_platform:  # a site key sees its own site and nothing else
        result["sites"] = [x for x in result["sites"] if x["slug"] == ctx.site_slug]
        result["count"] = len(result["sites"])
    return result


@router.post("/sites")
def upsert_site(body: SiteUpsert, x_site_key: str | None = Header(default=None)) -> dict:
    _check_site_key(x_site_key)
    return service.upsert_site(body.slug, name=body.name,
                               site_type=body.site_type, base_url=body.base_url,
                               settings=body.settings)


class ProvisionRequest(BaseModel):
    slug: str = Field(max_length=63)
    name: str = Field(default="", max_length=200)
    site_type: str = "custom"           # custom | wordpress
    base_url: str = Field(default="", max_length=300)
    settings: dict[str, Any] | None = None
    key_label: str = Field(default="", max_length=120)
    key_scopes: list[str] | None = None  # default: read + write
    rotate_key: bool = False
    check_health: bool = True


@router.post("/provision")
def provision_site(body: ProvisionRequest, x_site_key: str | None = Header(default=None)) -> dict:
    """Onboard a site in one call: create/update it, mint its scoped API key (shown once) and check that it can
    reach its CMS. Idempotent. Platform key only."""
    _check_site_key(x_site_key)
    result = service.provision_site(
        body.slug, name=body.name, site_type=body.site_type, base_url=body.base_url, settings=body.settings,
        key_label=body.key_label, key_scopes=body.key_scopes, rotate_key=body.rotate_key,
        check_health=body.check_health, via="sdk")
    if "error" in result:
        raise EngineHTTPError(result, 400 if "invalid" in result["error"] or "unknown scope" in result["error"] else None)
    return result


@router.delete("/sites/{site_slug}")
def delete_site(site_slug: str, x_site_key: str | None = Header(default=None)) -> dict:
    _check_site_key(x_site_key)
    return _resolve(service.delete_site(site_slug))


class KeyCreate(BaseModel):
    label: str = ""
    # any of: read, write, approve, publish, admin. Empty = ["read"] (least privilege).
    scopes: list[str] | None = None


@router.get("/sites/{site_slug}/keys")
def list_site_keys(site_slug: str, x_site_key: str | None = Header(default=None)) -> dict:
    """List a site's API keys (prefix, label, scopes, last used, revoked). Never the secret."""
    _check_site_key(x_site_key)
    return _resolve(site_keys.list_site_keys(site_slug))


@router.post("/sites/{site_slug}/keys")
def create_site_key(site_slug: str, body: KeyCreate | None = None,
                    x_site_key: str | None = Header(default=None)) -> dict:
    """Mint a per-site API key. The plaintext `key` in the response is shown ONCE."""
    _check_site_key(x_site_key)
    body = body or KeyCreate()
    result = site_keys.create_site_key(site_slug, label=body.label, scopes=body.scopes, via="sdk")
    if "error" in result and "unknown scope" in result["error"]:
        raise EngineHTTPError(result, 400)
    return _resolve(result)


@router.delete("/sites/{site_slug}/keys/{key_id}")
def revoke_site_key(site_slug: str, key_id: int,
                    x_site_key: str | None = Header(default=None)) -> dict:
    """Revoke a key immediately (the row is kept for the audit trail)."""
    _check_site_key(x_site_key)
    return _resolve(site_keys.revoke_site_key(site_slug, key_id, via="sdk"))


@router.get("/search-console")
def search_console_status(x_site_key: str | None = Header(default=None)) -> dict:
    """Per-site Search Console connectivity (multi-property, one SA).

    Property resolves per site (settings override, else base_url + "/");
    `connected` compares it against the properties the instance's
    GOOGLE_CREDENTIALS service account can access (one sites.list call).
    Tri-state: true / false / null when the check couldn't run."""
    _check_site_key(x_site_key)
    return service.get_search_console_status()


class WpTestPayload(BaseModel):
    base_url: str | None = None
    username: str | None = None
    app_password: str | None = None


@router.post("/sites/{site_slug}/test-connection")
def test_site_connection(site_slug: str, body: WpTestPayload | None = None,
                         x_site_key: str | None = Header(default=None)) -> dict:
    _check_site_key(x_site_key)
    cfg = body.model_dump() if body else None
    return service.test_wp_connection(site_slug, wp_config=cfg)


@router.get("/sites/{site_slug}/cadence")
def site_cadence(site_slug: str, x_site_key: str | None = Header(default=None)) -> dict:
    _check_site_key(x_site_key)
    return _resolve(service.site_cadence(site_slug))


@router.get("/sites/{site_slug}/health")
def site_health(site_slug: str, x_site_key: str | None = Header(default=None)) -> dict:
    _check_site_key(x_site_key)
    return _resolve(service.site_health(site_slug))


@router.get("/sites/{site_slug}/llms.txt")
def llms_txt(site_slug: str, x_site_key: str | None = Header(default=None)) -> dict:
    """Compose the site's llms.txt (§5.8 GEO) from its published articles.

    Returns JSON {"site", "count", "llms_txt"} — the site serves the text at
    its own /llms.txt URL. Companion to the per-article markdown_alternate.
    """
    _check_site_key(x_site_key)
    return _resolve(service.llms_txt(site_slug))


@router.get("/sites/{site_slug}/sitemap.xml")
def sitemap_xml(site_slug: str, x_site_key: str | None = Header(default=None)) -> dict:
    """Compose the site's XML sitemap (§5.6) from its published articles.

    Returns JSON {"site", "count", "sitemap_xml"} — the site serves the XML
    at its own /sitemap.xml URL (WordPress sites use core sitemaps instead).
    """
    _check_site_key(x_site_key)
    return _resolve(service.sitemap_xml(site_slug))


# --- Operator console backing (spec-site2-postgres-frontend §5) ---


@router.get("/sites/{site_slug}/queue")
def get_queue(site_slug: str, status: str = "", limit: int = 100,
              x_site_key: str | None = Header(default=None)) -> dict:
    """Keyword-ledger view (read-only): rows + per-status counts for the
    console queue screen and dashboard counters."""
    _check_site_key(x_site_key)
    return _resolve(service.list_queue(site_slug, status=status, limit=limit))


@router.get("/sites/{site_slug}/brief")
def get_brief(site_slug: str, x_site_key: str | None = Header(default=None)) -> dict:
    """Next briefable keyword (read-only peek, highest priority first).
    Returns {"status": "empty"} when the queue has nothing briefable."""
    _check_site_key(x_site_key)
    return _resolve(service.get_brief(site_slug))


@router.get("/sites/{site_slug}/research")
def get_research(site_slug: str, status: str = "", limit: int = 100,
                 x_site_key: str | None = Header(default=None)) -> dict:
    """research_data worksheet view (read-only): keyword rows with their
    research snapshot — subject, summary, primary/secondary keywords,
    Generated flag — for the console Research screen."""
    _check_site_key(x_site_key)
    return _resolve(service.list_research(site_slug, status=status, limit=limit))


@router.get("/sites/{site_slug}/briefs")
def get_briefs(site_slug: str, limit: int = 100,
               x_site_key: str | None = Header(default=None)) -> dict:
    """content_briefs worksheet view (read-only): rows whose snapshot
    carries a brief — brief content, FAQs, sources, summary — for the
    console Briefs screen."""
    _check_site_key(x_site_key)
    return _resolve(service.list_briefs(site_slug, limit=limit))


@router.get("/logs")
def get_logs(kind: str = "", limit: int = 200, offset: int = 0, site_slug: str = "",
             x_site_key: str | None = Header(default=None)) -> dict:
    """Logs worksheet view (read-only): audit_log rows (kind = action
    prefix, e.g. "usage" or "publish"; empty = all) + the cost ledger.
    `offset` pages the surfaced list(s) — the console's Older/Newer pager."""
    _check_site_key(x_site_key)
    # A site key sees its own rows only; the platform key may pass a site or omit it for everything.
    return _resolve(service.list_logs(kind=kind, limit=limit, offset=offset,
                                      site_slug=_ctx().scoped_site(site_slug)))


@router.get("/spend/summary")
def get_spend_summary(site_slug: str = "",
                      x_site_key: str | None = Header(default=None)) -> dict:
    """Aggregated SQL spend summary (WTD, MTD, Total) for mission control dashboard."""
    _check_site_key(x_site_key)
    return service.get_spend_summary(site_slug=_ctx().scoped_site(site_slug))


@router.patch("/articles/{article_id}/content")
def patch_content(article_id: int, body: ContentPatch,
                  x_site_key: str | None = Header(default=None)) -> dict:
    """Operator edit of an article's markdown; an approved article is
    reopened to generated so the approve gate runs on the edited text."""
    _check_site_key(x_site_key)
    return _resolve(service.update_content(article_id, body.content_md,
                                           note=body.note))


class MetaPatch(BaseModel):
    """The editable meta fields. Typed so a list/object/oversized value is a 422 at the door instead of being
    str()-ed into the article (ENG-17). Unknown keys are ignored, as before."""
    title: str | None = Field(default=None, max_length=300)
    slug: str | None = Field(default=None, max_length=200)
    focus_keyword: str | None = Field(default=None, max_length=200)
    summary: str | None = Field(default=None, max_length=2000)
    tldr: str | None = Field(default=None, max_length=1500)


@router.patch("/articles/{article_id}/meta")
def patch_meta(article_id: int, body: MetaPatch,
               x_site_key: str | None = Header(default=None)) -> dict:
    """Operator PATCH of allowed meta fields (title / slug / focus_keyword /
    summary / tldr). Only allowlisted keys are applied; every other meta key
    stays untouched. An approved article is reopened to generated so the approve
    gate can re-run on the new fields; a published article keeps its status."""
    _check_site_key(x_site_key)
    return _resolve(service.patch_article_meta(article_id, body.model_dump(exclude_none=True)))


_running_stages: set[str] = set()
_run_lock = threading.Lock()


@router.get("/stages")
def get_stages(limit: int = 200,
               x_site_key: str | None = Header(default=None)) -> dict:
    """Stage history + live running set (console Wave 5, read-only).

    History = newest `stage.run` audit rows (one per finished run, written by
    the run route); running = this engine process's in-flight stages."""
    _check_site_key(x_site_key)
    with _run_lock:
        running = sorted(_running_stages)
    return _resolve(service.list_stages(running=running, limit=limit))


@router.post("/run/{stage}", status_code=202)
def run_stage(stage: str, background_tasks: BackgroundTasks,
              body: StageRunRequest | None = None,
              x_site_key: str | None = Header(default=None)) -> dict:
    """Trigger a legacy pipeline stage in the background (console).

    Wraps scripts/run_stage.STAGE_HANDLERS — the same stage functions the
    scheduler runs. One concurrent run per stage (409 on overlap)."""
    _check_site_key(x_site_key)
    site_slug = (body.site_slug if body and body.site_slug else "").strip()
    try:
        from scripts import run_stage as run_stage_mod
    except Exception as e:  # pragma: no cover - env-dependent import
        raise HTTPException(status_code=503,
                            detail=f"run_stage engine not importable: {e}")
    handlers = getattr(run_stage_mod, "STAGE_HANDLERS", {})
    if stage not in handlers:
        raise HTTPException(status_code=404,
                            detail=f"unknown stage '{stage}' — valid: {sorted(handlers)}")
    with _run_lock:
        if stage in _running_stages:
            raise HTTPException(status_code=409,
                                detail=f"stage '{stage}' is already running")
        _running_stages.add(stage)
    # ...and across worker processes: `--workers 2` has two copies of the set above, so the same stage could
    # start twice. The lease lives in the database and expires, so a killed run cannot block the stage forever.
    from lib import lease as _lease
    if _lease.claim(f"stage:{stage}", ttl=3600) is False:
        with _run_lock:
            _running_stages.discard(stage)
        raise HTTPException(status_code=409, detail=f"stage '{stage}' is already running on another worker")

    def _invoke() -> None:
        try:
            started = datetime.now(timezone.utc)
            t0 = time.monotonic()
            ok, detail = True, ""
            try:
                asyncio.run(handlers[stage]())
            except Exception as e:
                ok, detail = False, f"{type(e).__name__}: {e}"
                raise
            finally:
                try:
                    service.record_stage_run(
                        stage, ok=ok, detail=detail,
                        duration_ms=int((time.monotonic() - t0) * 1000),
                        started_at=started)
                except Exception:  # telemetry must never mask the stage outcome
                    logger.exception("stage.run record failed for %r", stage)
        finally:
            with _run_lock:
                _running_stages.discard(stage)
            _lease.release(f"stage:{stage}")

    background_tasks.add_task(_invoke)
    out = {"status": "accepted", "stage": stage}
    if site_slug:
        # This used to set os.environ["SITE_SLUG"] around the run. Nothing ever read
        # it, and the mutation raced between concurrent requests, so it only made the
        # request LOOK site-scoped. Stage handlers still run against this instance's
        # configured site; say so instead of implying otherwise (plan ENG-05). True
        # per-site stages arrive with the TenantContext work (Phase 2).
        out["site_slug"] = site_slug
        out["warning"] = ("stage handlers are not site-scoped yet: this ran against the "
                          "instance's configured site, not necessarily "
                          f"'{site_slug}'. Run it on that site's own engine instance.")
    return out


@router.get("/wp/posts/{post_id}")
def wp_post(post_id: int, x_site_key: str | None = Header(default=None)) -> dict:
    """Read a WordPress post back (raw content + registered SEO meta) — the
    refresh/decay read path."""
    _check_site_key(x_site_key)
    return _resolve(service.wp_post(post_id))


# --- Elementor (§5.11/§5.13 — native REST target) ---


@router.get("/elementor/available")
def elementor_available(x_site_key: str | None = Header(default=None)) -> dict:
    """Preflight: 200 always — the body carries available/flag or error+next."""
    _check_site_key(x_site_key)
    return service.elementor_available()


@router.get("/elementor/posts/{post_id}")
def elementor_document(post_id: int, post_type: str = "posts",
                       x_site_key: str | None = Header(default=None)) -> dict:
    _check_site_key(x_site_key)
    return _resolve(service.elementor_document(post_id, post_type=post_type))


@router.post("/elementor/posts/{post_id}")
def elementor_save(post_id: int, body: ElementorSave,
                   x_site_key: str | None = Header(default=None)) -> dict:
    _check_site_key(x_site_key)
    return _resolve(service.elementor_save(post_id, body.elements,
                                           post_type=body.post_type,
                                           page_settings=body.page_settings))


@router.post("/elementor/articles/{article_id}/build")
def elementor_build(article_id: int, body: ElementorBuild | None = None,
                    x_site_key: str | None = Header(default=None)) -> dict:
    _check_site_key(x_site_key)
    result = service.elementor_build(article_id,
                                     post_id=(body.post_id if body else None),
                                     mode=(body.mode if body else "draft"))
    if "error" in result:
        if "not found" in result["error"] or "no content" in result["error"]:
            raise EngineHTTPError(result, 404)
        raise EngineHTTPError(result, 400)
    return result
