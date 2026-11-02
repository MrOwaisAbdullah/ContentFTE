"""Authorization for the REST API: which keys may call which route, on which tenant's data.

`authorize` is a router-level dependency, so it runs for EVERY `/sdk/v1` route before the handler.
It authenticates the key (sdk/auth.py), then — for site-scoped keys — looks the route up in ROUTES
below and enforces it. The platform (master) key passes straight through.

Why a table instead of per-handler checks: the old design left it to each of ~40 handlers to
remember to scope itself, and none did (plan SEC-03). Here the policy is data you can read in one
screen and test exhaustively, and **a route that is not listed is refused to site keys** — so a new
endpoint is platform-only until someone decides otherwise.

Rule kinds
    PLATFORM   platform key only (cross-tenant, secrets, or an outbound-request surface).
    SITE_PATH  the `{site_slug}` path segment must be the key's own site.
    ARTICLE    `{article_id}` must belong to the key's site (a foreign id is "not found").
    KEYWORD    `{keyword_id}` must belong to the key's site.
    SELF       the route takes the site as a query parameter / body field / returns a list; the
               HANDLER pins it with `AuthContext.scoped_site()` or filters its result. The table
               still gates the scope; tests/test_site_key_isolation.py proves each SELF route.
"""
from __future__ import annotations

from fastapi import Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select

from lib.db import Article, KeywordLedger, get_session, init_db
from sdk.auth import AuthContext, authenticate, set_current

PLATFORM, SITE_PATH, ARTICLE, KEYWORD, SELF = "platform", "site_path", "article", "keyword", "self"

P = "/sdk/v1"
# (method, route template) -> (rule kind, required scope)
ROUTES: dict[tuple[str, str], tuple[str, str]] = {
    # --- articles -----------------------------------------------------------------------------
    ("POST", f"{P}/articles"): (SELF, "write"),
    ("GET", f"{P}/articles"): (SELF, "read"),
    ("GET", f"{P}/articles/stats"): (SELF, "read"),
    ("GET", f"{P}/articles/{{article_id}}"): (ARTICLE, "read"),
    ("GET", f"{P}/articles/{{article_id}}/content"): (ARTICLE, "read"),
    ("GET", f"{P}/articles/{{article_id}}/gate"): (ARTICLE, "read"),
    ("GET", f"{P}/articles/{{article_id}}/images/{{name}}"): (ARTICLE, "read"),
    ("POST", f"{P}/articles/{{article_id}}/generate"): (ARTICLE, "write"),
    ("POST", f"{P}/articles/{{article_id}}/stage-images"): (ARTICLE, "write"),
    ("POST", f"{P}/articles/{{article_id}}/images/{{name}}/regenerate"): (ARTICLE, "write"),
    ("PATCH", f"{P}/articles/{{article_id}}/content"): (ARTICLE, "write"),
    ("PATCH", f"{P}/articles/{{article_id}}/meta"): (ARTICLE, "write"),
    ("POST", f"{P}/articles/{{article_id}}/approve"): (ARTICLE, "approve"),
    ("POST", f"{P}/articles/{{article_id}}/publish"): (ARTICLE, "publish"),
    ("POST", f"{P}/articles/{{article_id}}/refresh"): (ARTICLE, "publish"),
    ("POST", f"{P}/elementor/articles/{{article_id}}/build"): (ARTICLE, "publish"),
    ("DELETE", f"{P}/articles/{{article_id}}"): (ARTICLE, "admin"),
    # --- keywords -----------------------------------------------------------------------------
    ("POST", f"{P}/keywords/{{keyword_id}}/prioritize"): (KEYWORD, "write"),
    ("DELETE", f"{P}/keywords/{{keyword_id}}"): (KEYWORD, "admin"),
    # --- a site's own read-only views ---------------------------------------------------------
    ("GET", f"{P}/sites"): (SELF, "read"),                       # handler filters to the key's site
    ("GET", f"{P}/sites/{{site_slug}}/cadence"): (SITE_PATH, "read"),
    ("GET", f"{P}/sites/{{site_slug}}/health"): (SITE_PATH, "read"),
    ("GET", f"{P}/sites/{{site_slug}}/llms.txt"): (SITE_PATH, "read"),
    ("GET", f"{P}/sites/{{site_slug}}/sitemap.xml"): (SITE_PATH, "read"),
    ("GET", f"{P}/sites/{{site_slug}}/queue"): (SITE_PATH, "read"),
    ("GET", f"{P}/sites/{{site_slug}}/brief"): (SITE_PATH, "read"),
    ("GET", f"{P}/sites/{{site_slug}}/research"): (SITE_PATH, "read"),
    ("GET", f"{P}/sites/{{site_slug}}/briefs"): (SITE_PATH, "read"),
    ("GET", f"{P}/spend/summary"): (SELF, "read"),
    # --- platform only ------------------------------------------------------------------------
    ("POST", f"{P}/sites"): (PLATFORM, "admin"),                 # create/edit a site (and its secrets)
    ("POST", f"{P}/provision"): (PLATFORM, "admin"),             # one-call onboarding: site + scoped key
    ("DELETE", f"{P}/sites/{{site_slug}}"): (PLATFORM, "admin"),
    ("GET", f"{P}/sites/{{site_slug}}/keys"): (PLATFORM, "admin"),      # a key must not mint keys
    ("POST", f"{P}/sites/{{site_slug}}/keys"): (PLATFORM, "admin"),
    ("DELETE", f"{P}/sites/{{site_slug}}/keys/{{key_id}}"): (PLATFORM, "admin"),
    # sends caller-supplied credentials to a caller-supplied URL (SSRF) until safe_fetch exists:
    ("POST", f"{P}/sites/{{site_slug}}/test-connection"): (PLATFORM, "admin"),
    ("GET", f"{P}/search-console"): (PLATFORM, "admin"),         # spans every site on the instance
    ("GET", f"{P}/logs"): (SELF, "read"),                        # handler pins `site_slug` to the key's site
    ("GET", f"{P}/stages"): (PLATFORM, "admin"),
    ("POST", f"{P}/run/{{stage}}"): (PLATFORM, "admin"),         # stage handlers are not site-scoped yet
    ("GET", f"{P}/wp/posts/{{post_id}}"): (PLATFORM, "admin"),   # resolves WP credentials from process env
    ("GET", f"{P}/elementor/available"): (PLATFORM, "admin"),
    ("GET", f"{P}/elementor/posts/{{post_id}}"): (PLATFORM, "admin"),
    ("POST", f"{P}/elementor/posts/{{post_id}}"): (PLATFORM, "admin"),
}


def _owner_of_article(article_id: int):
    init_db()
    s = get_session()
    try:
        return s.execute(select(Article.site_id).where(Article.id == article_id)).scalar_one_or_none()
    finally:
        s.close()


def _owner_of_keyword(keyword_id: int):
    init_db()
    s = get_session()
    try:
        return s.execute(select(KeywordLedger.site_id).where(KeywordLedger.id == keyword_id)).scalar_one_or_none()
    finally:
        s.close()


def _deny(status: int, detail: str):
    raise HTTPException(status_code=status, detail=detail)


async def authorize(request: Request, x_site_key: str | None = Header(default=None)) -> AuthContext:
    """Router-level dependency: authenticate, then enforce ROUTES for site-scoped keys."""
    ctx = await run_in_threadpool(authenticate, x_site_key)
    # Set in the request's own task (this is an async dependency) so the sync handlers, which run in
    # a copy of this context, can read it with sdk.auth.current().
    set_current(ctx)
    request.state.auth = ctx
    if ctx.is_platform:
        return ctx

    route = request.scope.get("route")
    template = getattr(route, "path", "") or ""
    rule = ROUTES.get((request.method.upper(), template))
    if rule is None:                                   # fail closed: unlisted => platform-only
        _deny(403, "this endpoint is not available to site API keys")
    kind, scope = rule
    if kind == PLATFORM:
        _deny(403, "this endpoint requires the platform key")
    if not ctx.allows(scope):
        _deny(403, f"this key lacks the '{scope}' scope")

    params = request.path_params
    if kind == SITE_PATH and params.get("site_slug") != ctx.site_slug:
        _deny(403, f"this key is not valid for site '{params.get('site_slug')}'")
    elif kind == ARTICLE:
        owner = await run_in_threadpool(_owner_of_article, int(params["article_id"]))
        if owner is not None and owner != ctx.site_id:
            # same answer as a missing article: don't confirm that a foreign id exists
            _deny(404, f"article {params['article_id']} not found")
    elif kind == KEYWORD:
        owner = await run_in_threadpool(_owner_of_keyword, int(params["keyword_id"]))
        if owner is not None and owner != ctx.site_id:
            _deny(404, f"keyword {params['keyword_id']} not found")
    return ctx
