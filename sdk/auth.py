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
