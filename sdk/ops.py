"""Operational alerts (OPS-01): the conditions that should wake a human, computed from the database.

    collect_alerts() -> [{"severity": "critical"|"warning", "code": str, "site": str, "message": str}, ...]

* `not_ready`        the engine's own readiness check (database / auth / tenancy) is failing
* `budget_exceeded`  a site hit its monthly spend cap - its generation is refused until next month
* `budget_warning`   a site has used >= 90% of its cap
* `cadence_overdue`  a site with a posting cadence has published nothing for twice that interval

Pure reads, never raises. `scripts/alerts_check.py` posts the result to Discord; the same function backs any
dashboard. Uptime ("is the process answering at all?") is the separate probe in .github/workflows/uptime.yml,
because an engine that is down cannot report that it is down.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

BUDGET_WARN_AT = 0.9


def _alert(severity: str, code: str, site: str, message: str) -> Dict[str, Any]:
    return {"severity": severity, "code": code, "site": site, "message": message}


def collect_alerts(now: datetime | None = None) -> List[Dict[str, Any]]:
    from sqlalchemy import select

    from lib.db import Article, Site, get_session, init_db
    from sdk import service
    from sdk.health import readiness

    now = now or datetime.now(timezone.utc)
    alerts: List[Dict[str, Any]] = []
    try:
        ready = readiness()
        if not ready.get("ready"):
            alerts.append(_alert("critical", "not_ready", "", "engine readiness failing: " + "; ".join(
                f"{k}: {v.get('detail') or v.get('error') or 'failing'}"
                for k, v in (ready.get("checks") or {}).items() if isinstance(v, dict) and not v.get("ok", True))))
    except Exception as exc:  # noqa: BLE001
        alerts.append(_alert("critical", "not_ready", "", f"readiness check raised {type(exc).__name__}"))

    try:
        from lib.outbox import pending_summary
        ob = pending_summary()
        if ob["dead"]:
            alerts.append(_alert("critical", "delivery_failed", "",
                                 f"{ob['dead']} site delivery(ies) gave up after every retry; the site never "
                                 "received those articles (re-publish them, or fix the site's webhook)"))
        elif ob["pending"] >= 20:
            alerts.append(_alert("warning", "delivery_backlog", "",
                                 f"{ob['pending']} site deliveries are waiting to be retried"))
    except Exception:  # noqa: BLE001
        pass

    try:
        init_db()
        s = get_session()
        try:
            for site in s.execute(select(Site).order_by(Site.id)).scalars():
                b = service.budget_status(s, site)
                if b.get("exceeded"):
                    alerts.append(_alert("critical", "budget_exceeded", site.slug,
                                         f"monthly spend ${b['mtd_usd']} reached the ${b['cap_usd']} cap; "
                                         "generation is blocked until next month or the cap is raised"))
                elif b.get("cap_usd") and b["mtd_usd"] >= BUDGET_WARN_AT * b["cap_usd"]:
                    alerts.append(_alert("warning", "budget_warning", site.slug,
                                         f"spent ${b['mtd_usd']} of the ${b['cap_usd']} monthly cap"))
                cad = service.get_site_cadence_status(s, site)
                interval = service.CADENCE_INTERVALS.get(str(cad.get("frequency") or ""))
                if interval is not None:
                    last = s.execute(
                        select(Article.published_at).where(Article.site_id == site.id, Article.status == "published")
                        .order_by(Article.published_at.desc()).limit(1)).scalar()
                    if last is not None:
                        if last.tzinfo is None:
                            last = last.replace(tzinfo=timezone.utc)
                        if now - last > 2 * interval:
                            days = (now - last).days
                            alerts.append(_alert("warning", "cadence_overdue", site.slug,
                                                 f"last publish was {days} days ago on a "
                                                 f"'{cad.get('frequency')}' cadence"))
        finally:
            s.close()
    except Exception as exc:  # noqa: BLE001
        alerts.append(_alert("warning", "alerts_error", "", f"alert collection failed: {type(exc).__name__}"))
    return alerts


def format_alerts(alerts: List[Dict[str, Any]]) -> str:
    if not alerts:
        return ""
    icon = {"critical": "🔴", "warning": "🟠"}
    lines = [f"{icon.get(a['severity'], '•')} **{a['code']}**" + (f" ({a['site']})" if a["site"] else "")
             + f": {a['message']}" for a in alerts]
    return "ContentFTE alerts:\n" + "\n".join(lines)
