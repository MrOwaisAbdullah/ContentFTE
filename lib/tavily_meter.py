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

from sqlalchemy import select
from sqlalchemy.orm import Session

from lib.db import TavilyUsage, get_session, init_db
from lib.store import DEFAULT_SITE_SLUG, get_or_create_site

logger = logging.getLogger(__name__)


def monthly_budget() -> int:
    try:
        return int(os.environ.get("TAVILY_MONTHLY_BUDGET") or "1000")
    except ValueError:
        return 1000


def _month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def check_and_increment(session: Session, site_slug: str = "", n: int = 1) -> Dict[str, Any]:
    """Increment this month's Tavily counter and report whether calls remain.

    Returns {allowed, used, budget, remaining, exhausted, month}. `allowed`
    is False once used >= budget (the caller should pause-and-flag)."""
    site = get_or_create_site(session, site_slug)
    month = _month()
    budget = monthly_budget()
    row = session.execute(
        select(TavilyUsage).where(TavilyUsage.site_id == site.id, TavilyUsage.month == month)
    ).scalar_one_or_none()
    if row is None:
        row = TavilyUsage(site_id=site.id, month=month, calls=0)
        session.add(row)
        session.commit()
        session.refresh(row)
    used_before = row.calls
    allowed = used_before < budget
    if allowed:
        row.calls = used_before + n
        session.commit()
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
            budget = monthly_budget()
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
