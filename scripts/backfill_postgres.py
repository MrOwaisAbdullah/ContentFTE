"""Backfill Postgres from the existing Google Sheets (Sheets → Postgres cutover).

Usage:
    python scripts/backfill_postgres.py [--dry-run] [--site SLUG]

Reads `research_data`, `content_briefs`, `generated_posts` and upserts each row
through `lib/store.py` (the same mappers the live dual-write uses), so a
backfill and a live run converge to identical rows. Idempotent: re-running is a
no-op (keyword/article upserts are keyed on site+keyword / site+title).

`approved_unpublished` is a FILTER view of `generated_posts` — deliberately not
backfilled (it would just re-upsert the same articles).
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Any, Callable, Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.db import get_session, init_db
from lib.store import (
    get_or_create_site,
    map_brief_row,
    map_generated_post_row,
    map_research_row,
    mirror_article,
    mirror_brief,
    mirror_keyword,
    verify_cutover,
)

logger = logging.getLogger(__name__)

# Order matters only for readability; upserts are order-independent.
BACKFILL_ORDER = [
    ("research_data", "keyword"),
    ("content_briefs", "brief"),
    ("generated_posts", "article"),
]


def _default_fetch(worksheet_name: str) -> List[Dict[str, Any]]:
    """Reads a worksheet as records (dict keyed by header). Lazy import so
    tests and dry tooling don't need Sheets creds."""
    from tools.sheet_tool import manage_sheet_data

    res = manage_sheet_data(worksheet_name=worksheet_name, action="get_all_records")
    if res.get("status") != "success":
        logger.warning(f"fetch '{worksheet_name}' failed: {res.get('message')}")
        return []
    return res.get("data") or []


def backfill(fetch_records: Callable[[str], List[Dict[str, Any]]] = _default_fetch,
             dry_run: bool = False, site_slug: str = "") -> Dict[str, Any]:
    init_db()
    session = get_session()
    counts: Dict[str, int] = {"keyword": 0, "brief": 0, "article": 0}
    try:
        for worksheet, kind in BACKFILL_ORDER:
            records = fetch_records(worksheet) or []
            for rec in records:
                headers = list(rec.keys())
                row = [rec[h] for h in headers]
                if dry_run:
                    counts[kind] += 1
                    continue
                if kind == "keyword":
                    mirror_keyword(session, site_slug=site_slug,
                                   **map_research_row(row, headers))
                elif kind == "brief":
                    mirror_brief(session, site_slug=site_slug,
                                 **map_brief_row(row, headers))
                elif kind == "article":
                    mirror_article(session, site_slug=site_slug,
                                   **map_generated_post_row(row, headers))
                counts[kind] += 1
        verify = None
        if not dry_run:
            get_or_create_site(session, site_slug)
            verify = verify_cutover(session, site_slug)
        return {"status": "ok", "counts": counts, "verify": verify, "dry_run": dry_run}
    finally:
        session.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Backfill Postgres from Google Sheets")
    ap.add_argument("--dry-run", action="store_true", help="count rows only; write nothing")
    ap.add_argument("--site", default="", help="site slug to attribute rows to")
    args = ap.parse_args()

    res = backfill(dry_run=args.dry_run, site_slug=args.site)
    print(f"[backfill] dry_run={res['dry_run']} counts={res['counts']} verify={res['verify']}")


if __name__ == "__main__":
    main()
