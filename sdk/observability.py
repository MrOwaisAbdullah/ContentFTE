"""Request ids and structured logs (ENG-21).

Every request gets an id (the caller's `X-Request-ID` if it is sane, else a fresh one), echoed back in the
response header and attached to every log line written while handling it, so one failing call can be followed
from the console through the engine's logs. `LOG_FORMAT=json` switches the root logger to one JSON object per
line for log shippers; the default human format is unchanged.

Only the request PATH is logged - never the query string (it can carry tokens) and never a body or header.
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import time
import uuid
from typing import Any

_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
_SANE_ID = re.compile(r"^[A-Za-z0-9._\-]{8,64}$")
access_log = logging.getLogger("contentfte.access")


def current_request_id() -> str:
    return _request_id.get()


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", _request_id.get()),
        }
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        for key in ("method", "path", "status", "ms", "site"):
            if hasattr(record, key):
                out[key] = getattr(record, key)
        return json.dumps(out, ensure_ascii=False, default=str)


def configure_logging() -> None:
    """Idempotent. Adds the request-id filter to the root handlers and, with LOG_FORMAT=json, the JSON
    formatter. Called once at import of main."""
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper())
    use_json = (os.environ.get("LOG_FORMAT") or "").strip().lower() == "json"
    for handler in root.handlers:
        if not any(isinstance(f, RequestIdFilter) for f in handler.filters):
            handler.addFilter(RequestIdFilter())
        if use_json and not isinstance(handler.formatter, JsonFormatter):
            handler.setFormatter(JsonFormatter())
    access_log.setLevel(logging.INFO)


class RequestIdMiddleware:
    """Pure-ASGI (not BaseHTTPMiddleware, which would buffer streaming MCP responses)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        supplied = ""
        for k, v in scope.get("headers") or []:
            if k == b"x-request-id":
                supplied = v.decode("latin-1", "replace")
                break
        rid = supplied if _SANE_ID.match(supplied) else uuid.uuid4().hex
        token = _request_id.set(rid)
        started = time.perf_counter()
        status = {"code": 0}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
                headers = list(message.get("headers") or [])
                headers.append((b"x-request-id", rid.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            path = scope.get("path", "")
            if path not in ("/health", "/ready"):      # probes would drown the log
                access_log.info("%s %s -> %s", scope.get("method", ""), path, status["code"], extra={
                    "method": scope.get("method", ""), "path": path, "status": status["code"],
                    "ms": round((time.perf_counter() - started) * 1000, 1)})
            _request_id.reset(token)
