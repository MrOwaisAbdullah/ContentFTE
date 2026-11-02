"""Database-backed leases and idempotency records (ENG-03, ENG-14, OPS-02).

The engine's single-flight (one publish / one generation per article) and its Idempotency-Key replay used to
live in process memory. The container runs `uvicorn --workers 2` and the pipeline runs in separate processes, so
two requests landing on different workers both "won". These two tables make the guarantees hold across
processes and restarts, using only a UNIQUE constraint - the one primitive every database (SQLite and Postgres)
gives atomically:

    claim("publish:42", ttl=600)    -> True for exactly one caller until released or expired
    release("publish:42")
    idem_get / idem_put             -> replay a stored response for 24h

A lease carries an expiry so a worker that is killed mid-publish cannot wedge an article forever: the next
caller takes over once `ttl` seconds have passed. Both functions fail OPEN-to-process-local on a database error
(callers fall back to their in-memory guard), because losing the guarantee across workers is better than
refusing to publish at all.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, OperationalError

from lib.db import IdempotencyRecord, Lease, get_session, init_db

HOLDER = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
DEFAULT_TTL = 900
IDEMPOTENCY_TTL = 24 * 3600


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def claim(key: str, ttl: int = DEFAULT_TTL) -> Optional[bool]:
    """True = you hold the lease; False = someone else does; None = the database could not be used (caller
    falls back to its process-local guard)."""
    try:
        init_db()
        s = get_session()
        try:
            for _ in range(2):
                try:
                    s.add(Lease(key=key, holder=HOLDER, expires_at=_now() + timedelta(seconds=ttl)))
                    s.commit()
                    return True
                except IntegrityError:
                    s.rollback()
                    row = s.execute(select(Lease).where(Lease.key == key)).scalar_one_or_none()
                    if row is None:
                        continue                       # released between our insert and read: try once more
                    if _aware(row.expires_at) > _now():
                        return row.holder == HOLDER and _renew(s, row, ttl)
                    # expired: take it over with a conditional UPDATE so only one taker wins
                    taken = s.execute(
                        Lease.__table__.update()
                        .where(Lease.key == key, Lease.holder == row.holder, Lease.expires_at == row.expires_at)
                        .values(holder=HOLDER, expires_at=_now() + timedelta(seconds=ttl)))
                    s.commit()
                    return taken.rowcount == 1
            return False
        finally:
            s.close()
    except (OperationalError, Exception):  # noqa: BLE001 - never block the work on the lock table
        return None


def _renew(s, row, ttl: int) -> bool:
    row.expires_at = _now() + timedelta(seconds=ttl)
    s.commit()
    return True


def release(key: str) -> None:
    try:
        init_db()
        s = get_session()
        try:
            s.execute(delete(Lease).where(Lease.key == key, Lease.holder == HOLDER))
            s.commit()
        finally:
            s.close()
    except Exception:  # noqa: BLE001
        pass


def idem_get(key: str) -> Optional[dict]:
    try:
        init_db()
        s = get_session()
        try:
            row = s.execute(select(IdempotencyRecord).where(IdempotencyRecord.key == key)).scalar_one_or_none()
            if row is None:
                return None
            if _aware(row.created_at) + timedelta(seconds=IDEMPOTENCY_TTL) < _now():
                s.delete(row)
                s.commit()
                return None
            return json.loads(row.response) if row.response else None
        finally:
            s.close()
    except Exception:  # noqa: BLE001
        return None


def idem_put(key: str, response: dict[str, Any]) -> None:
    try:
        init_db()
        s = get_session()
        try:
            s.add(IdempotencyRecord(key=key, response=json.dumps(response, default=str)))
            s.commit()
        except IntegrityError:
            s.rollback()                                # a concurrent identical request stored it first
        finally:
            s.close()
    except Exception:  # noqa: BLE001
        pass


def purge_expired() -> int:
    """Housekeeping: drop expired leases and old idempotency rows. Returns rows removed."""
    try:
        init_db()
        s = get_session()
        try:
            a = s.execute(delete(Lease).where(Lease.expires_at < _now())).rowcount or 0
            b = s.execute(delete(IdempotencyRecord).where(
                IdempotencyRecord.created_at < _now() - timedelta(seconds=IDEMPOTENCY_TTL))).rowcount or 0
            s.commit()
            return int(a + b)
        finally:
            s.close()
    except Exception:  # noqa: BLE001
        return 0
