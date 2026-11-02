"""Persistent delivery outbox for custom-site webhooks (ADP-04).

`custom_site.deliver` retries a few times in-process. If the process dies mid-retry, or the site is down for an hour,
those retries are gone and the site never hears about the article. A delivery that did not succeed immediately is
therefore written to the `delivery_outbox` table and retried later with exponential backoff, under the SAME
`delivery_id` (so the receiver can de-duplicate a retry that overlapped a slow success).

    enqueue(site_id, article_id, url, payload, delivery_id)   after a failed first attempt
    process_due(now)                                          called by scripts/process_outbox.py on a schedule
    pending_summary()                                         counts for the alerts (sdk/ops.py)

The signing secret is NOT stored in the outbox; it is re-read from the site's (encrypted) settings at send time, so
rotating it takes effect for queued deliveries and a database dump of the outbox reveals no key.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional

from sqlalchemy import select

from lib.db import DeliveryOutbox, Site, get_session, init_db

MAX_ATTEMPTS = 8
BACKOFF_BASE_S = 60            # 1m, 2m, 4m, ... capped at 6h


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def _backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(6 * 3600, BACKOFF_BASE_S * (2 ** max(0, attempts - 1))))


def enqueue(site_id: int, article_id: Optional[int], url: str, payload: Dict[str, Any], delivery_id: str,
            error: str = "") -> int:
    init_db()
    s = get_session()
    try:
        row = DeliveryOutbox(site_id=site_id, article_id=article_id, url=url, delivery_id=delivery_id,
                             payload=json.dumps(payload, default=str, ensure_ascii=False), attempts=1,
                             status="pending", last_error=(error or "")[:300],
                             next_attempt_at=_now() + _backoff(1))
        s.add(row)
        s.commit()
        return row.id
    finally:
        s.close()


def process_due(now: Optional[datetime] = None,
                send: Optional[Callable[..., Dict[str, Any]]] = None, limit: int = 50) -> Dict[str, int]:
    """Attempt every pending delivery whose time has come. Returns {sent, retried, dead}."""
    from lib import custom_site
    from sdk import service

    send = send or custom_site.deliver
    now = now or _now()
    init_db()
    s = get_session()
    tally = {"sent": 0, "retried": 0, "dead": 0}
    try:
        rows = s.execute(select(DeliveryOutbox).where(DeliveryOutbox.status == "pending")
                         .order_by(DeliveryOutbox.id.asc()).limit(limit)).scalars().all()
        for row in rows:
            if _aware(row.next_attempt_at) and _aware(row.next_attempt_at) > now:
                continue
            site = s.get(Site, row.site_id)
            _, secret = service._delivery_target(site)
            res = send(json.loads(row.payload), webhook_url=row.url, secret=secret,
                       delivery_id=row.delivery_id, max_attempts=1)
            row.attempts += 1
            if res.get("status") == "ok":
                row.status, row.last_error, row.delivered_at = "delivered", "", now
                tally["sent"] += 1
            elif row.attempts >= MAX_ATTEMPTS:
                row.status, row.last_error = "dead", str(res.get("message") or "")[:300]
                tally["dead"] += 1
            else:
                row.last_error = str(res.get("message") or "")[:300]
                row.next_attempt_at = now + _backoff(row.attempts)
                tally["retried"] += 1
        s.commit()
        return tally
    finally:
        s.close()


def pending_summary() -> Dict[str, int]:
    """{'pending': n, 'dead': n} - for alerting."""
    from sqlalchemy import func
    try:
        init_db()
        s = get_session()
        try:
            rows = s.execute(select(DeliveryOutbox.status, func.count()).group_by(DeliveryOutbox.status)).all()
            counts = {k: int(v) for k, v in rows}
            return {"pending": counts.get("pending", 0), "dead": counts.get("dead", 0)}
        finally:
            s.close()
    except Exception:  # noqa: BLE001
        return {"pending": 0, "dead": 0}
