"""§5.10-7 Tavily metering — per site, per month.

When a site's monthly Tavily budget is exhausted, research tools must
**pause-and-flag** rather than keep going and publish an under-researched
article. This module owns the counter + the guard; the search tools call it.

Pure DB (no network). Env `TAVILY_MONTHLY_BUDGET` (default 1000) and
`DEFAULT_SITE_SLUG`. Never raises.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lib.db import TavilyUsage, get_session, init_db
from lib.store import DEFAULT_SITE_SLUG, get_or_create_site

logger = logging.getLogger(__name__)


def monthly_budget(site=None) -> int:
    """The month's call budget: this site's own `settings.budget.tavily_monthly` when set, else the process-wide
    TAVILY_MONTHLY_BUDGET (default 1000). One shared number let a single busy tenant spend everyone's quota
    (TEN-03)."""
    own = ((getattr(site, "settings", None) or {}).get("budget") or {}).get("tavily_monthly") if site is not None else None
    for raw in (own, os.environ.get("TAVILY_MONTHLY_BUDGET")):
        try:
            if raw not in (None, ""):
                return max(0, int(float(raw)))
        except (TypeError, ValueError):
            continue
    return 1000


def _month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _usage_row(session: Session, site_id: int, month: str) -> TavilyUsage:
    row = session.execute(
        select(TavilyUsage).where(TavilyUsage.site_id == site_id, TavilyUsage.month == month)
    ).scalar_one_or_none()
    if row is not None:
        return row
    try:
        row = TavilyUsage(site_id=site_id, month=month, calls=0)
        session.add(row)
        session.commit()
        session.refresh(row)
        return row
    except IntegrityError:           # two workers created it at once: the unique key makes the loser re-read
        session.rollback()
        return session.execute(
            select(TavilyUsage).where(TavilyUsage.site_id == site_id, TavilyUsage.month == month)
        ).scalar_one()


def check_and_increment(session: Session, site_slug: str = "", n: int = 1) -> Dict[str, Any]:
    """Increment this month's Tavily counter and report whether calls remain.

    Returns {allowed, used, budget, remaining, exhausted, month}. `allowed` is False once used >= budget (the
    caller should pause-and-flag).

    The increment is ONE conditional UPDATE (`calls = calls + n WHERE calls < budget`), so two concurrent
    callers cannot both read the same value and both write back value+1 (a lost update that under-counted
    spend), and the budget can never be overshot by a race (ENG-12)."""
    site = get_or_create_site(session, site_slug)
    month = _month()
    budget = monthly_budget(site)
    row = _usage_row(session, site.id, month)
    result = session.execute(
        update(TavilyUsage)
        .where(TavilyUsage.id == row.id, TavilyUsage.calls < budget)
        .values(calls=TavilyUsage.calls + n)
    )
    session.commit()
    allowed = result.rowcount == 1
    session.refresh(row)
    used = row.calls
    return {
        "allowed": allowed,
        "used": used,
        "budget": budget,
        "remaining": max(budget - used, 0),
        "exhausted": used >= budget,
        "month": month,
        "site": site.slug,
    }


def meter(site_slug: str = "", n: int = 1) -> Dict[str, Any]:
    """Session-owning convenience wrapper. Never raises (fail-open: allowed)."""
    try:
        init_db()
        session = get_session()
        try:
            return check_and_increment(session, site_slug, n)
        finally:
            session.close()
    except Exception as e:
        logger.warning(f"tavily metering failed (fail-open): {e}")
        return {"allowed": True, "used": 0, "budget": monthly_budget(),
                "remaining": monthly_budget(), "exhausted": False,
                "month": _month(), "site": site_slug or DEFAULT_SITE_SLUG, "error": str(e)}


def budget_status(site_slug: str = "") -> Dict[str, Any]:
    try:
        init_db()
        session = get_session()
        try:
            site = get_or_create_site(session, site_slug)
            budget = monthly_budget(site)
            row = session.execute(
                select(TavilyUsage).where(
                    TavilyUsage.site_id == site.id, TavilyUsage.month == _month())
            ).scalar_one_or_none()
            used = row.calls if row else 0
            return {"site": site.slug, "month": _month(), "used": used, "budget": budget,
                    "remaining": max(budget - used, 0), "exhausted": used >= budget}
        finally:
            session.close()
    except Exception as e:
        return {"error": str(e)}
