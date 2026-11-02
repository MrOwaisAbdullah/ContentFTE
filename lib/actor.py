"""Who is acting, for the audit trail (OPS-01 "audit actor").

A context variable the API layer sets once per request (sdk/auth.py -> `set_actor`) and the database layer reads
when it writes an `audit_log` row (lib/db.py stamps `payload["actor"]`). Keeping it here, free of imports, lets
`lib/` record the actor without depending on `sdk/`. Outside a request (a CLI job, a pipeline stage) it is "".
"""
from __future__ import annotations

from contextvars import ContextVar

_actor: ContextVar[str] = ContextVar("audit_actor", default="")


def set_actor(label: str):
    """Set the acting identity (e.g. "platform" or "site:acme/prod-key"); returns the reset token."""
    return _actor.set(label or "")


def current_actor() -> str:
    return _actor.get()
