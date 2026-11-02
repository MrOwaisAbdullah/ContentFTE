"""Optional error tracking (OPS-01). Off unless SENTRY_DSN is set and `sentry-sdk` is installed.

    pip install "contentfte[monitoring]"      # or: uv sync --extra monitoring
    SENTRY_DSN=https://...  SENTRY_ENVIRONMENT=production  SENTRY_TRACES=0

Nothing is sent by default and the engine never requires the package. Events are scrubbed BEFORE they leave the
process: request bodies, cookies and auth headers are dropped, and every string is passed through
`lib.redact.redact_text`, so a stack trace that happened to contain a WordPress password or an API key does not
become a Sentry issue. `send_default_pii` stays False.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)
_initialised = False

_DROP_KEYS = {"authorization", "cookie", "set-cookie", "x-site-key", "x-api-key", "x-webhook-secret"}


def scrub_event(event: dict, hint: Optional[dict] = None) -> Optional[dict]:
    """Sentry `before_send`: strip request bodies/credentials and redact secrets in every string."""
    from lib.redact import redact_text

    def walk(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: ("[Filtered]" if str(k).lower() in _DROP_KEYS else walk(v)) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v) for v in value]
        if isinstance(value, str):
            return redact_text(value)
        return value

    req = event.get("request")
    if isinstance(req, dict):
        req.pop("data", None)
        req.pop("cookies", None)
        req.pop("query_string", None)           # may carry ?secret= / ?apikey=
    return walk(event)


def init_sentry() -> bool:
    """Initialise Sentry if configured. Returns True when it is active. Never raises."""
    global _initialised
    dsn = (os.environ.get("SENTRY_DSN") or "").strip()
    if _initialised or not dsn:
        return _initialised
    try:
        import sentry_sdk  # type: ignore
    except ImportError:
        logger.warning("SENTRY_DSN is set but sentry-sdk is not installed; error tracking is off "
                       "(install the 'monitoring' extra)")
        return False
    try:
        sentry_sdk.init(
            dsn=dsn,
            environment=os.environ.get("SENTRY_ENVIRONMENT") or "production",
            release=os.environ.get("SENTRY_RELEASE") or None,
            traces_sample_rate=float(os.environ.get("SENTRY_TRACES") or 0),
            send_default_pii=False,
            before_send=scrub_event,
        )
        _initialised = True
        logger.info("Sentry error tracking enabled")
    except Exception as exc:  # noqa: BLE001 - monitoring must never stop the engine from starting
        logger.warning("Sentry init failed: %s", exc)
    return _initialised
