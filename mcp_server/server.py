"""contentfte_mcp — §5.13 MCP server: let AI assistants (Claude Code, etc.)
drive the ContentFTE pipeline directly.

Layering: sdk/service.py (canonical ops) -> REST API (sdk/server.py) ->
this MCP server (thin consumer of the same service). MCP never touches the
DB directly, so the API contract stays the single source of truth and the
two surfaces cannot drift.

Spec tools: list_sites, get_brief, generate_article, get_article_status,
get_image, publish_article, site_health — prefixed `contentfte_` per MCP
naming convention so they never collide with other servers (e.g. WordPress's
own MCP adapter, which stays the route for deep site ops per §5.11).

Transport: FastAPI-mounted streamable HTTP at `/mcp` (see main.py, single-
server architecture; `streamable_http_path="/"` set at init) or stdio via
`python -m mcp_server.server` for local Claude Code configs.

No LLM calls here — the MCP *client* is the LLM; tools are pure DB/HTTP.
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


class GenerateArticleInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    site_slug: str = Field(..., min_length=1, max_length=100,
                            description="Site slug the article belongs to")
    keyword: str = Field(..., min_length=2, max_length=300,
                         description="Target keyword/topic, e.g. 'best crm for agencies'")


class ArticleIdInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    article_id: int = Field(..., ge=1, description="Numeric article ID (from contentfte_generate_article)")


class PublishArticleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    article_id: int = Field(..., ge=1, description="Numeric article ID to publish")
    mode: Literal["draft", "auto"] = Field(
        default="draft",
        description="'draft' = create as WP draft (default for new sites); 'auto' = publish live")


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
    annotations={"title": "Create Article from Keyword", "readOnlyHint": False,
                 "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def generate_article(params: GenerateArticleInput) -> str:
    """Create an article record in 'briefed' state for a site + keyword.

    Idempotent per (site, keyword): an existing article for the same title
    is returned instead of duplicated. Event emitted: article.ready.

    Args:
        params (GenerateArticleInput): site_slug + keyword.

    Returns:
        str: JSON {"id": int, "status": "briefed", "event": "article.ready",
        "deduplicated"?: bool} or {"error", "next"}.
    """
    return _out(service.submit_article(params.site_slug, keyword=params.keyword,
                                       brief={"title": params.keyword}))


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
    POST /sdk/v1/articles/{id}/approve (or the SDK client).

    Args:
        params (PublishArticleInput): article_id + mode ("draft"|"auto").

    Returns:
        str: JSON {"id", "status": "published", "mode",
        "event": "article.published"} or {"error", "next"} explaining why
        the gate refused (e.g. status is not yet 'approved').
    """
    return _out(service.publish_article(params.article_id, mode=params.mode, via="mcp"))


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


def main() -> None:
    """Stdio entry point: `python -m mcp_server.server` (local Claude Code)."""
    mcp.run()


if __name__ == "__main__":
    main()
