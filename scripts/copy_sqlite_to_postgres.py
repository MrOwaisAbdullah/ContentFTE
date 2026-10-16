"""Copy the whole sqlite store into Postgres (the DATABASE_URL switch).

Usage:
    python scripts/copy_sqlite_to_postgres.py [--source sqlite:///./contentfte.db]
                                              [--target postgresql+psycopg://...]
                                              [--dry-run]

The engine, SDK, console, Discord worker and stage scripts all read/write
through `lib.db` (DATABASE_URL). Flipping a live install from the local
sqlite file to Postgres is: create the database -> point DATABASE_URL at it
-> run this script once to move every row over -> restart.

- Rows are copied in FK-safe table order with their primary keys preserved,
  so article_id links in cost_ledger / audit_log stay intact.
- Re-running is safe: every row is merged by primary key, so a second run is
  a no-op and also propagates later edits. Run it against a *fresh* database
  (a target that already has different rows with the same unique keys, e.g.
  a Sheets backfill, would collide — use scripts/backfill_postgres.py for
  that legacy path instead).
- When the target is Postgres the id sequences are advanced past MAX(id)
  afterwards, so the next INSERT doesn't collide with copied ids.
- Naive datetimes (sqlite stores UTC without an offset) are pinned to UTC
  before they enter a timestamptz column, so wall times never shift.

Exit code is non-zero on any error, so it's scriptable.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, select, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from lib.db import (  # noqa: E402
    Article,
    AuditLog,
    Base,
    BrandProfile,
    CostLedger,
    KeywordLedger,
    SeoCache,
    ShareOfVoice,
    Site,
    TavilyUsage,
)

# FK-safe copy order: parents before children.
MODELS = [Site, BrandProfile, KeywordLedger, Article, CostLedger, AuditLog,
          SeoCache, ShareOfVoice, TavilyUsage]


def _row_dict(model, row) -> dict:
    """Column values of one ORM row, UTC-pinned for datetime columns."""
    data = {c.name: getattr(row, c.name) for c in model.__table__.columns}
    for key, value in data.items():
        if isinstance(value, datetime) and value.tzinfo is None:
            data[key] = value.replace(tzinfo=timezone.utc)
    return data


def _reset_sequences(engine) -> None:
    """Advance Postgres identity sequences past MAX(id) per table."""
    with engine.begin() as conn:
        for model in MODELS:
            table = model.__tablename__
            conn.execute(text(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {table}), 0) + 1, false)"))


def copy_store(source_url: str, target_url: str, *, dry_run: bool = False,
               log=print) -> dict:
    """Copy every table (ids preserved) from source to target.

    Returns a report: {"tables": {name: {"read", "written"}}, ...}. `dry_run`
    counts source rows and writes nothing (the target is never even opened).
    """
    source = create_engine(source_url, pool_pre_ping=True)
    target = create_engine(target_url, pool_pre_ping=True)
    report: dict = {"source": source_url, "target": target_url,
                    "dry_run": bool(dry_run), "tables": {},
                    "sequences_reset": False}
    try:
        if not dry_run:
            Base.metadata.create_all(target)  # additions only (checkfirst)
        src = Session(source)
        dst = Session(target)
        try:
            for model in MODELS:
                name = model.__tablename__
                rows = src.execute(select(model)).scalars().all()
                written = 0
                for row in rows:
                    if not dry_run:
                        dst.merge(model(**_row_dict(model, row)))
                        written += 1
                if not dry_run:
                    dst.commit()
                report["tables"][name] = {"read": len(rows), "written": written}
                log(f"  {name:16} read={len(rows):5} written={written:5}")
            if not dry_run and target.dialect.name == "postgresql":
                _reset_sequences(target)
                report["sequences_reset"] = True
                log("  postgres identity sequences advanced past MAX(id)")
        finally:
            src.close()
            dst.close()
    finally:
        source.dispose()
        target.dispose()
    return report


def _default_source() -> str:
    return "sqlite:///" + os.path.join(os.getcwd(), "contentfte.db").replace("\\", "/")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", default=_default_source(),
                    help="source store URL (default: sqlite:///./contentfte.db)")
    ap.add_argument("--target", default=os.environ.get("DATABASE_URL", ""),
                    help="target store URL (default: DATABASE_URL env var)")
    ap.add_argument("--dry-run", action="store_true",
                    help="count rows per table, write nothing")
    args = ap.parse_args()
    if not args.target:
        print("error: no target — pass --target or set DATABASE_URL",
              file=sys.stderr)
        return 2
    if args.source.rstrip("/") == args.target.rstrip("/"):
        print("error: source and target are the same URL", file=sys.stderr)
        return 2
    try:
        report = copy_store(args.source, args.target, dry_run=args.dry_run)
    except Exception as exc:  # noqa: BLE001 — CLI: report and exit non-zero
        print(f"error: {exc}", file=sys.stderr)
        return 1
    total = sum(t["written"] for t in report["tables"].values())
    print(("dry run: would copy " if args.dry_run else "copied ")
          + f"{total} rows to {args.target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
