"""Liveness vs readiness (plan ENG-21).

`/health` only says the process is up. It answered "OK" even with the database unreachable or no API
key configured, so a load balancer or Dokploy kept routing traffic to an engine that could not serve
any request. `/ready` reports whether this instance can actually do its job:

  * the database answers a query;
  * requests can be authenticated at all (a master key is set, or dev mode is explicitly on);
and shows the tenancy mode. It never returns secrets - only booleans and the redacted error text.
"""
from __future__ import annotations

from typing import Any, Dict

from lib.redact import redact_text
from lib.site_env import tenancy_mode
from sdk.auth import master_key, unauthenticated_allowed


def readiness() -> Dict[str, Any]:
    checks: Dict[str, Any] = {}
    ready = True

    try:
        from lib.db import get_engine, init_db
        init_db()
        engine = get_engine()
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        checks["database"] = {"ok": True, "dialect": engine.dialect.name}
    except Exception as exc:  # noqa: BLE001 - any failure here means "not ready", with the reason
        ready = False
        checks["database"] = {"ok": False, "error": redact_text(f"{type(exc).__name__}: {exc}")[:300]}

    keyed, dev = bool(master_key()), unauthenticated_allowed()
    auth_ok = keyed or dev
    ready = ready and auth_ok
    checks["auth"] = {
        "ok": auth_ok,
        "master_key_configured": keyed,
        "unauthenticated_dev_mode": dev and not keyed,
        **({} if auth_ok else {"error": "no SDK_MASTER_KEY set: every request would be refused (503)"}),
    }
    checks["tenancy"] = {"mode": tenancy_mode()}
    return {"ready": ready, "checks": checks}
