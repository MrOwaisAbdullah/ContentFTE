"""Single API-key check shared by every engine surface (REST, MCP, legacy routes).

Plan refs: SEC-01 (`/mcp` was mounted with no authentication) and SEC-02 (an unset
`SDK_MASTER_KEY` silently opened every route, and the comparison was not
constant-time).

Behaviour
---------
* `SDK_MASTER_KEY` set    -> the request must present it (header ``X-Site-Key`` or
  ``Authorization: Bearer <key>``). Compared in constant time.
* `SDK_MASTER_KEY` unset  -> **fail closed** (503 with a precise message) unless
  ``SDK_ALLOW_UNAUTHENTICATED=1`` is set explicitly. That flag is for a developer's
  own machine; never set it on a host that anyone else can reach.

This module deliberately knows nothing about sites or tenants: it answers
"may this caller talk to this engine at all?". Binding a key to one site is the
per-tenant scoping work in the plan (Phase 2) and builds on this single choke point.
"""
from __future__ import annotations

import hmac
import os
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Optional

from fastapi import HTTPException

_TRUTHY = ("1", "true", "yes", "on")


def master_key() -> str:
    return os.environ.get("SDK_MASTER_KEY", "").strip()


def unauthenticated_allowed() -> bool:
    return os.environ.get("SDK_ALLOW_UNAUTHENTICATED", "").strip().lower() in _TRUTHY


def keys_equal(provided: Optional[str], expected: str) -> bool:
    """Constant-time comparison (no early exit on the first differing byte)."""
    if not provided or not expected:
        return False
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


def bearer_token(authorization: Optional[str]) -> Optional[str]:
    """`Authorization: Bearer <token>` -> `<token>`; anything else -> None."""
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    return token.strip() or None if scheme.lower() == "bearer" else None


def check_key(provided: Optional[str]) -> str:
    """Raise `HTTPException` unless `provided` is acceptable; return a caller label."""
    expected = master_key()
    if not expected:
        if unauthenticated_allowed():
            return "dev"
        raise HTTPException(
            status_code=503,
            detail=("SDK_MASTER_KEY is not configured on this engine, so it refuses "
                    "requests. Set SDK_MASTER_KEY (and the same value as the console "
                    "instance apiKey), or set SDK_ALLOW_UNAUTHENTICATED=1 for local "
                    "development only."),
        )
    if not keys_equal(provided, expected):
        raise HTTPException(status_code=401, detail="invalid X-Site-Key")
    return provided or ""


ALL_SCOPES = frozenset({"read", "write", "approve", "publish", "admin"})


@dataclass(frozen=True)
class AuthContext:
    """Who is calling. `platform` = the master key (every site, platform-wide routes);
    `site` = a per-site key bound to exactly one site and a set of scopes (see sdk/keys.py)."""

    kind: str                               # "platform" | "site"
    label: str = ""
    site_id: Optional[int] = None
    site_slug: str = ""
    scopes: frozenset = field(default_factory=frozenset)
    key_id: Optional[int] = None

    @property
    def is_platform(self) -> bool:
        return self.kind == "platform"

    def allows(self, scope: str) -> bool:
        """`admin` implies every scope, and any scope implies `read`."""
        if self.is_platform or "admin" in self.scopes:
            return True
        if scope == "read":
            return bool(self.scopes)
        return scope in self.scopes

    def scoped_site(self, requested: str = "") -> str:
        """The site a query/body parameter must resolve to. A site key is pinned to its own site:
        omitting the parameter means "mine", naming another site is refused."""
        if self.is_platform:
            return requested or ""
        if requested and requested != self.site_slug:
            raise HTTPException(status_code=403, detail=f"this key is not valid for site '{requested}'")
        return self.site_slug


_current: ContextVar[Optional[AuthContext]] = ContextVar("sdk_auth_context", default=None)


def set_current(ctx: Optional[AuthContext]):
    # also publish who is acting to the audit layer (lib/actor.py -> stamped on every audit_log row)
    from lib.actor import set_actor
    set_actor("" if ctx is None else (
        "platform" if ctx.is_platform else f"site:{ctx.site_slug}/{ctx.label or ctx.key_id or 'key'}"))
    return _current.set(ctx)


def current() -> Optional[AuthContext]:
    """The AuthContext of the request being served (None outside an authenticated request)."""
    return _current.get()


def authenticate(provided: Optional[str]) -> AuthContext:
    """Resolve a presented key to an AuthContext, or raise 401/503.

    Order matters: the master key is compared first (so a master key that merely *looks* like a site
    key still works), then per-site keys, then the closed-by-default platform check."""
    expected = master_key()
    if expected and keys_equal(provided, expected):
        return AuthContext(kind="platform", label="platform", scopes=ALL_SCOPES)
    from sdk import keys  # local import: keys -> lib.db, keep auth importable without a database
    if keys.looks_like_site_key(provided):
        found = keys.lookup(provided)
        if found is None:
            raise HTTPException(status_code=401, detail="invalid X-Site-Key")
        return AuthContext(kind="site", label=found["label"], site_id=found["site_id"],
                           site_slug=found["site_slug"], scopes=frozenset(found["scopes"]),
                           key_id=found["key_id"])
    label = check_key(provided)          # raises 401 (wrong key) / 503 (no key configured)
    return AuthContext(kind="platform", label=label, scopes=ALL_SCOPES)


class KeyAuthMiddleware:
    """ASGI wrapper that applies `check_key` to everything it fronts (used for `/mcp`).

    Accepts the key as ``X-Site-Key`` (same as REST) or ``Authorization: Bearer``
    (what most MCP clients can be configured to send). Non-HTTP scopes (lifespan)
    pass through untouched.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        from starlette.datastructures import Headers
        from starlette.responses import JSONResponse

        headers = Headers(scope=scope)
        provided = headers.get("x-site-key") or bearer_token(headers.get("authorization"))
        try:
            check_key(provided)
        except HTTPException as exc:
            response = JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
