"""One place that turns a service error dict into an HTTP status and a machine-readable code (ENG-16).

The service returns `{"error": msg, "next": hint, "code"?: ...}`. REST used to answer 404 for nearly every
one of those (a bad enum value, a state conflict and a missing row all looked the same) and re-derived the
real status at each route by searching the message for substrings; the `next` hint that MCP shows was
dropped on the way out. Now:

    classify(result) -> (code, http_status)       explicit `code` wins, else the message is classified here
    EngineHTTPError(result, status=None)          an HTTPException whose body is
                                                  {"detail": msg, "code": code, "next": hint}

`detail` stays a plain string, so existing clients keep working; `code` and `next` are additive.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Tuple

from fastapi import HTTPException
from fastapi.responses import JSONResponse

# explicit codes the service sets itself
CODE_STATUS = {
    "budget_exceeded": 402,
    "gate_failed": 409,
    "publish_in_progress": 409,
    "generation_in_progress": 409,
    "not_found": 404,
    "invalid_input": 400,
    "invalid_state": 409,
    "conflict": 409,
    "rate_limited": 429,
    "upstream_failed": 502,
    "not_configured": 424,
}


def classify(result: Mapping[str, Any]) -> Tuple[str, int]:
    """(code, http_status) for a service error dict."""
    code = str(result.get("code") or "")
    if code in CODE_STATUS:
        return code, CODE_STATUS[code]
    msg = str(result.get("error") or "")
    low = msg.lower()
    if "cadence limit reached" in low:
        return "rate_limited", 429
    if "not found" in low or low.endswith("has no content") or "no content" in low:
        return "not_found", 404
    if (low.startswith(("invalid", "unsupported", "no allowlisted")) or "use 'draft'" in low
            or "must be" in low):
        return "invalid_input", 400
    if "requires 'approved'" in msg or "already being" in low or "is already" in low:
        return "invalid_state", 409
    if low.startswith(("generation failed", "agent returned", "generated content", "wp refresh failed",
                       "wordpress push failed")):
        return "upstream_failed", 502
    if "not configured" in low:
        return "not_configured", 424
    # Unclassified: keep the historical 404 rather than guess, but still hand back a code a client can switch on.
    return code or "error", 404


class EngineHTTPError(HTTPException):
    """HTTPException that also carries the machine-readable `code` and the `next` hint."""

    def __init__(self, result: Mapping[str, Any], status: Optional[int] = None):
        code, default_status = classify(result)
        super().__init__(status_code=status or default_status, detail=str(result.get("error") or "error"))
        self.code = code
        self.next = str(result.get("next") or "")


async def engine_error_handler(_request, exc: EngineHTTPError) -> JSONResponse:
    body: dict = {"detail": exc.detail, "code": exc.code}
    if exc.next:
        body["next"] = exc.next
    return JSONResponse(body, status_code=exc.status_code, headers=getattr(exc, "headers", None))


def install(app) -> None:
    """Register the handler. Without it EngineHTTPError still works - FastAPI's default handler renders it
    as a plain {"detail": ...} - so routers mounted on a bare app degrade gracefully."""
    app.add_exception_handler(EngineHTTPError, engine_error_handler)
