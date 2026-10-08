"""contentfte_mcp — §5.13 MCP server: let AI assistants (Claude Code, etc.)
drive the ContentFTE pipeline directly.

Layering: sdk/service.py (canonical ops) -> REST API (sdk/server.py) ->
this MCP server (thin consumer of the same service). MCP never touches the
DB directly, so the API contract stays the single source of truth and the
two surfaces cannot drift.

Spec tools: list_sites, get_brief, generate_article, get_article_status,
get_image, publish_article, site_health, elementor_available/_document/
_save/_build — prefixed `contentfte_` per MCP naming convention so they
never collide with other servers (e.g. WordPress's own MCP adapter). The
elementor_* tools ride native REST document meta (Elementor >= 3.27,
§5.13) — no third-party MCP server is required for layout writes.

Transport: FastAPI-mounted streamable HTTP at `/mcp` (see main.py, single-
server architecture; `streamable_http_path="/"` set at init) or stdio via
`python -m mcp_server.server` for local Claude Code configs.

content_generator_agent through service.generate_content (briefed -> drafted)
— this server holds no model logic of its own; every other tool is pure
DB/HTTP, and the MCP *client* remains the LLM driving the workflow.
"""
from __future__ import annotations

import json
import os
from typing import Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, ConfigDict, Field

from sdk import service

# FastMCP auto-enables DNS-rebinding protection for host=127.0.0.1 with an
# allow-list of localhost forms only — any other Host header (TestClient's
# "testserver", LAN IP, domain) gets 421 Misdirected Request. Keep protection
# ON but widen the allow-list; add extra hosts via MCP_ALLOWED_HOSTS env.
_extra_hosts = [h.strip() for h in os.environ.get("MCP_ALLOWED_HOSTS", "").split(",")
                if h.strip()]

# streamable_http_path MUST be a constructor arg (setting mcp.settings later
# is ignored); json_response=True enables plain JSON-RPC over HTTP.
mcp = FastMCP(
    "contentfte_mcp",
    instructions=(
        "ContentFTE SEO content pipeline: briefs, generation, status, "
        "images, publishing. Workflow: contentfte_list_sites -> "
        "contentfte_get_brief -> contentfte_generate_article -> "
        "contentfte_get_article_status -> contentfte_publish_article. "
        "Elementor (native REST, Elementor >= 3.27): "
        "contentfte_elementor_available -> contentfte_elementor_document -> "
        "contentfte_elementor_save (or contentfte_elementor_build to compose "
        "an article as a document). "
        "Same operations are exposed as REST under /sdk/v1/."
    ),
    streamable_http_path="/",
    json_response=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*",
                       "testserver", "testserver:*", *_extra_hosts],
        allowed_origins=["http://127.0.0.1:*", "http://localhost:*",
                         "http://[::1]:*"],
    ),
)


# ---------------------------------------------------------------------------
# Input models (Pydantic validation — constraints + descriptions)
# ---------------------------------------------------------------------------
class SiteSlugInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    site_slug: str = Field(..., min_length=1, max_length=100,
                            description="Site slug, e.g. 'acme' (from contentfte_list_sites)")


class ListArticlesInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    site_slug: str = Field(default="", max_length=100,
                           description="Optional site slug to scope the list (omit for all sites)")
    status: str = Field(default="", max_length=30,
                        description="Optional lifecycle filter: briefed|drafted|approved|"
                                    "published|needs_review (omit for all)")
    limit: int = Field(default=100, ge=1, le=500, description="Page size (max 500)")
    offset: int = Field(default=0, ge=0, description="Rows to skip (pagination)")


class GenerateArticleInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    site_slug: str = Field(..., min_length=1, max_length=100,
                           description="Site slug the article belongs to")
    keyword: str = Field(..., min_length=2, max_length=300,
                         description="Target keyword/topic, e.g. 'best crm for agencies'")
    regenerate: bool = Field(
        default=False,
        description="true = rewrite an article that already has content "
                    "(default false: generation is idempotent per article)")


class ArticleIdInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    article_id: int = Field(..., ge=1, description="Numeric article ID (from contentfte_generate_article)")


class WpPostInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    post_id: int = Field(..., ge=1,
                         description="WordPress post/page ID to read back "
                                     "(from publish's wp.post_id or meta.wp_post_id)")


class PublishArticleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    article_id: int = Field(..., ge=1, description="Numeric article ID to publish")
    mode: Literal["draft", "auto"] = Field(
        default="draft",
        description="'draft' = create as WP draft (default for new sites); 'auto' = publish live")


class ElementorPostInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    post_id: int = Field(..., ge=1, description="WordPress post/page ID to read the Elementor document from")
    post_type: Literal["posts", "pages"] = Field(
        default="posts", description="WP REST resource type ('posts' default, or 'pages')")


class ElementorSaveInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    post_id: int = Field(..., ge=1, description="WordPress post/page ID to write the document to")
    post_type: Literal["posts", "pages"] = Field(
        default="posts", description="WP REST resource type ('posts' default, or 'pages')")
    elements_json: str = Field(
        ..., min_length=2,
        description='JSON array string of root elements, e.g. '
                    '[{"id":"a1b2c3d","elType":"container","settings":{},"elements":[],"isInner":false}] '
                    '(fetch the current shape via contentfte_elementor_document)')
    page_settings_json: str = Field(
        default="",
        description='Optional JSON object string, e.g. {"hide_title":"yes"} — '
                    'omit/empty to keep the settings the editor owns')


class ElementorBuildInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    article_id: int = Field(..., ge=1, description="Numeric article ID to render as an Elementor document")
    post_id: int | None = Field(
        default=None, ge=1,
        description="Existing WP post ID — omit to create one (or reuse the article's meta.wp_post_id)")
    mode: Literal["draft", "auto"] = Field(
        default="draft",
        description="'draft' (default for new sites) | 'auto' = publish live")


def _out(data: dict) -> str:
    """Service result -> JSON string. Error dicts keep their `next` hint."""
    return json.dumps(data, default=str)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
@mcp.tool(
    name="contentfte_list_sites",
    annotations={"title": "List ContentFTE Sites", "readOnlyHint": True,
                 "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def list_sites() -> str:
    """List every site managed by ContentFTE (start here to get site slugs).

    Returns:
        str: JSON {"sites": [{"id", "slug", "name", "site_type", "base_url",
        "publish_mode"}], "count": int}.

    Examples:
        - Use first: to discover the site_slug for all other tools.
    """
    return _out(service.list_sites())


@mcp.tool(
    name="contentfte_list_articles",
    annotations={"title": "List Articles", "readOnlyHint": True,
                 "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def list_articles(params: ListArticlesInput) -> str:
    """List articles newest-first, optionally filtered by site and/or status.

    Enumerate a site's articles (e.g. status="published") to get their ids,
    then pull each one's rendered payload via GET /sdk/v1/articles/{id}/content
    — this is how a custom-site content loader discovers what to render.

    Args:
        params (ListArticlesInput): site_slug?, status?, limit?, offset?.

    Returns:
        str: JSON {"articles": [{"id", "site_id", "site_slug", "title", "slug",
        "status", "created_at", "published_at", "cost_usd"}], "count", "total",
        "limit", "offset"} or {"error", "next"} for an unknown site.
    """
    return _out(service.list_articles(site_slug=params.site_slug, status=params.status,
                                      limit=params.limit, offset=params.offset))


@mcp.tool(
    name="contentfte_get_brief",
    annotations={"title": "Get Next Briefable Keyword", "readOnlyHint": True,
                 "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def get_brief(params: SiteSlugInput) -> str:
    """Get the next briefable keyword (§5.16 ledger rule: briefs pull ONLY from
    approved/queued rows — highest priority_score first).

    Args:
        params (SiteSlugInput): site_slug — e.g. "acme".

    Returns:
        str: JSON {"keyword", "intent", "volume", "difficulty",
        "priority_score", "research_snapshot", "ledger_id"} or
        {"status": "empty", "hint": ...} when nothing is briefable, or
        {"error", "next"} when the site is unknown.
    """
    return _out(service.get_brief(params.site_slug))


@mcp.tool(
    name="contentfte_generate_article",
    annotations={"title": "Create and Generate Article", "readOnlyHint": False,
                 "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def generate_article(params: GenerateArticleInput) -> str:
    """Create an article for a site + keyword and run real generation (§5.5).

    One call does submit + generate: an article row is created (or the
    existing one for the same title is reused), then content_generator_agent
    writes the post from the in-memory brief and the row lands in 'drafted'.
    An article that already has content is returned as-is (deduplicated)
    unless regenerate=true. Next steps: contentfte_get_article_status ->
    approve (POST /sdk/v1/articles/{id}/approve) -> contentfte_publish_article.

    Args:
        params (GenerateArticleInput): site_slug, keyword, regenerate?.

    Returns:
        str: JSON {"id", "status": "drafted", "event": "article.drafted",
        "title", "words", "quality_score"?, "deduplicated"?, "has_content"?}
        or {"error", "next"} (unknown site/article, runner failure —
        generation is idempotent, so retry after fixing the cause).
    """
    submitted = service.submit_article(params.site_slug, keyword=params.keyword,
                                       brief={"title": params.keyword})
    if "error" in submitted:
        return _out(submitted)
    return _out(await service.generate_content(submitted["id"],
                                               regenerate=params.regenerate))


@mcp.tool(
    name="contentfte_get_article_status",
    annotations={"title": "Get Article Status and Scores", "readOnlyHint": True,
                 "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def get_article_status(params: ArticleIdInput) -> str:
    """Get an article's lifecycle status, eval sub-scores, and cost.

    Args:
        params (ArticleIdInput): article_id.

    Returns:
        str: JSON {"id", "status", "scores": {accuracy, depth, seo, voice,
        originality, citability}, "cost_usd", "keyword_id"}. Status flow:
        briefed -> drafted -> evaluated -> needs_review|approved -> published.
        Errors: {"error", "next"}.
    """
    return _out(service.get_article(params.article_id))


@mcp.tool(
    name="contentfte_get_image",
    annotations={"title": "Get Article Images", "readOnlyHint": True,
                 "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def get_image(params: ArticleIdInput) -> str:
    """Get the article's images (featured thumbnail + in-post) with prompts,
    model, cost, and IPTC provenance flags.

    Args:
        params (ArticleIdInput): article_id.

    Returns:
        str: JSON {"images": [{"slot": "featured"|"inpost", "url", "alt",
        "model", "cost_usd", "prompt", "provenance"}], "count": int}.
        Empty until images are generated. Errors: {"error", "next"}.
    """
    return _out(service.get_images(params.article_id))


@mcp.tool(
    name="contentfte_publish_article",
    annotations={"title": "Publish Article", "readOnlyHint": False,
                 "destructiveHint": True, "idempotentHint": True, "openWorldHint": True},
)
async def publish_article(params: PublishArticleInput) -> str:
    """Move an APPROVED article to published (draft or auto mode, §5.11).

    Draft mode is the default for new sites. Publishing requires the §5.2
    gate: overall score >=90 and every sub-score >=80, approved via
    POST /sdk/v1/articles/{id}/approve (or the SDK client). For
    site_type="wordpress" sites the same call pushes the post to WordPress
    (meta description, Article+FAQ JSON-LD, categories + tags — auto-derived
    with prefer-reuse against the site's existing taxonomy when the brief
    carries none — featured/in-post images) — the response carries
    {"wp": {"ok", "post_id", "url", "categories", "tags", ...}};
    best-effort fail-open, re-running publish retries a failed push.

    Args:
        params (PublishArticleInput): article_id + mode ("draft"|"auto").

    Returns:
        str: JSON {"id", "status": "published", "mode",
        "event": "article.published", "wp"?} or {"error", "next"}
        explaining why the gate refused (e.g. status is not yet 'approved').
    """
    return _out(service.publish_article(params.article_id, mode=params.mode, via="mcp"))


@mcp.tool(
    name="contentfte_refresh_article",
    annotations={"title": "Refresh Article", "readOnlyHint": False,
                 "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def refresh_article(params: ArticleIdInput) -> str:
    """Refresh an already-published article (§5.11 decay path).

    WordPress sites (site_type="wordpress"): updates the EXISTING post in place
    (content + SEO meta + taxonomy) — never creates a post and never changes
    its status. Requires the article to have been published (meta.wp_post_id).
    Custom sites have no push: re-pull GET /sdk/v1/articles/{id}/content.

    Args:
        params (ArticleIdInput): article_id.

    Returns:
        str: JSON {"ok", "event": "article.refreshed", "wp_post_id", "url",
        "status"} for WP, or {"ok", "render_target": "custom", "next"} for a
        custom site, or {"error", "next"}.
    """
    return _out(service.refresh_article(params.article_id, via="mcp"))


@mcp.tool(
    name="contentfte_stage_images",
    annotations={"title": "Stage Images", "readOnlyHint": False,
                 "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def stage_images(params: ArticleIdInput) -> str:
    """Generate + stage featured/in-post images into the article (§5.9).

    Section-aware: each in-post image is generated for one `## ` section
    (its own prompt + alt) and tagged after_h2 so publish injects it INLINE
    in the body, before the FAQ. Idempotent — articles that already have
    images are left untouched. publish_article runs the same staging
    automatically when images are missing; use this tool to pre-approve or
    retry. Without provider credentials it skips cleanly (no error).

    Args:
        params (ArticleIdInput): article_id.

    Returns:
        str: JSON {"id", "event": "article.images", "images", "featured",
        "inpost", "errors"?} or {"skipped", "reason"} or {"error", "next"}.
    """
    return _out(service.stage_images(params.article_id))


@mcp.tool(
    name="contentfte_wp_post",
    annotations={"title": "Read WordPress Post", "readOnlyHint": True,
                 "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def wp_post(params: WpPostInput) -> str:
    """Read a WordPress post back — raw block content + registered SEO meta
    (Yoast/RankMath/AIOSEO) — for the refresh/decay path.

    Usage: verify that a contentfte_refresh_article landed, read a post before
    updating it, or feed decay analysis. Requires WordPress to be configured
    (WP_BASE_URL/WP_USERNAME/WP_APP_PASSWORD).

    Args:
        params (WpPostInput): post_id (from publish's wp.post_id / meta.wp_post_id).

    Returns:
        str: JSON {"id", "slug", "status", "title", "content_raw", "excerpt",
        "url", "modified", "featured_media", "categories", "tags", "meta"}
        or {"error", "next"}.
    """
    return _out(service.wp_post(params.post_id))


@mcp.tool(
    name="contentfte_site_health",
    annotations={"title": "Site Health Check", "readOnlyHint": True,
                 "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def site_health(params: SiteSlugInput) -> str:
    """Health check for a site: ledger queue depth, published count, WP config.

    Args:
        params (SiteSlugInput): site_slug.

    Returns:
        str: JSON {"site", "ok": bool, "ledger": {"briefable", "published"},
        "wp_configured": bool, "checks": [str, ...]} — `checks` entries are
        actionable ("EMPTY queue — approve keywords"). Errors: {"error", "next"}.
    """
    return _out(service.site_health(params.site_slug))


@mcp.tool(
    name="contentfte_llms_txt",
    annotations={"title": "Get Site llms.txt", "readOnlyHint": True,
                 "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def llms_txt(params: SiteSlugInput) -> str:
    """Compose the site's llms.txt (§5.8 GEO) from its PUBLISHED articles.

    The agent-facing index a custom site serves at /llms.txt — the site-level
    companion to the per-article `markdown_alternate` (.md). The site owns the
    URL; the engine composes the content.

    Args:
        params (SiteSlugInput): site_slug.

    Returns:
        str: JSON {"site", "count", "llms_txt"} or {"error", "next"}.
    """
    return _out(service.llms_txt(params.site_slug))


@mcp.tool(
    name="contentfte_sitemap",
    annotations={"title": "Get Site XML Sitemap", "readOnlyHint": True,
                 "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def sitemap_xml(params: SiteSlugInput) -> str:
    """Compose the site's XML sitemap (§5.6, sitemaps.org 0.9) from PUBLISHED
    articles — loc per article, lastmod = publish date. Custom sites serve it
    at {base}/sitemap.xml; WordPress sites use their core sitemap instead.

    Args:
        params (SiteSlugInput): site_slug.

    Returns:
        str: JSON {"site", "count", "sitemap_xml"} or {"error", "next"}.
    """
    return _out(service.sitemap_xml(params.site_slug))


@mcp.tool(
    name="contentfte_elementor_available",
    annotations={"title": "Probe Elementor REST Meta", "readOnlyHint": True,
                 "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def elementor_available() -> str:
    """Probe the connected WordPress for Elementor document meta (Elementor
    >= 3.27 registers _elementor_data with show_in_rest).

    Returns:
        str: JSON {"available": bool, "meta_keys": [str, ...], "hint": str}
        — hint explains why availability is false (e.g. Elementor too old).
        Config problems come back as {"error", "next"}.
    """
    return _out(service.elementor_available())


@mcp.tool(
    name="contentfte_elementor_document",
    annotations={"title": "Read Elementor Document", "readOnlyHint": True,
                 "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
async def elementor_document(params: ElementorPostInput) -> str:
    """Read the current Elementor document (root elements + page settings).

    Element shape: {"id": 7-char hex, "elType": "container"|"widget",
    "widgetType"?, "settings": {...}, "elements": [...], "isInner": bool}.
    Use this output as elements_json for contentfte_elementor_save edits.

    Args:
        params (ElementorPostInput): post_id + post_type.

    Returns:
        str: JSON {"id", "url", "status", "is_elementor", "elements": [...],
        "element_count", "page_settings", "template_type"} — plus
        "parse_error" when _elementor_data could not be decoded.
        Errors: {"error", "next"}.
    """
    return _out(service.elementor_document(params.post_id, post_type=params.post_type))


@mcp.tool(
    name="contentfte_elementor_save",
    annotations={"title": "Write Elementor Document", "readOnlyHint": False,
                 "destructiveHint": True, "idempotentHint": True, "openWorldHint": True},
)
async def elementor_save(params: ElementorSaveInput) -> str:
    """Replace a post's Elementor document (full-document write, audited).

    Complex inputs arrive as JSON strings (strict tool schema):
        elements_json — JSON ARRAY of root elements (fetch the current
            shape via contentfte_elementor_document first).
        page_settings_json — optional JSON OBJECT; leave empty to keep
            the settings the Elementor editor owns.

    Args:
        params (ElementorSaveInput): post_id, post_type, elements_json,
        page_settings_json.

    Returns:
        str: JSON {"ok": true, "id", "url", "saved_elements", "cache_note",
        "post_id"} — cache_note warns that REST meta writes may leave the
        Elementor CSS stale until the next in-editor save. Errors:
        {"error", "next"}.
    """
    try:
        elements = json.loads(params.elements_json)
    except (ValueError, TypeError) as exc:
        return _out({"error": f"elements_json is not valid JSON: {exc}",
                     "next": 'expected a JSON array string, e.g. '
                             '[{"id":"a1b2c3d","elType":"container","settings":{},"elements":[]}]'})
    if not isinstance(elements, list):
        return _out({"error": "elements_json must decode to an array of root elements",
                     "next": "fetch the current shape via contentfte_elementor_document"})
    page_settings: dict | None = None
    if params.page_settings_json:
        try:
            page_settings = json.loads(params.page_settings_json)
        except (ValueError, TypeError) as exc:
            return _out({"error": f"page_settings_json is not valid JSON: {exc}",
                         "next": 'expected a JSON object string, e.g. {"hide_title":"yes"}'})
        if not isinstance(page_settings, dict):
            return _out({"error": "page_settings_json must decode to a JSON object",
                         "next": 'e.g. {"hide_title":"yes"}'})
    return _out(service.elementor_save(params.post_id, elements,
                                       post_type=params.post_type,
                                       page_settings=page_settings))


@mcp.tool(
    name="contentfte_elementor_build",
    annotations={"title": "Compose Article as Elementor Document", "readOnlyHint": False,
                 "destructiveHint": True, "idempotentHint": True, "openWorldHint": True},
)
async def elementor_build(params: ElementorBuildInput) -> str:
    """Compose an article's content as an Elementor document (WP render
    target "elementor", §5.11).

    Behavior: post_id (or the article's stored meta.wp_post_id) → save the
    layout onto that existing post; otherwise create the WP post first with
    plain-HTML fallback content (an Elementor write failure never
    re-creates/duplicates the post — it fails open and reports
    elementor.ok=false). Subsequent builds reuse meta.wp_post_id.

    Args:
        params (ElementorBuildInput): article_id, post_id?, mode.

    Returns:
        str: JSON {"article_id", "wp_post_id", "url", "status",
        "render_target": "elementor", "elementor": {...}} or
        {"error", "next"} (article missing, no content, WP not configured).
    """
    return _out(service.elementor_build(params.article_id, post_id=params.post_id,
                                        mode=params.mode))


def main() -> None:
    """Stdio entry point: `python -m mcp_server.server` (local Claude Code)."""
    mcp.run()


if __name__ == "__main__":
    main()
