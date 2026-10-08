"""Sheets vs Postgres drift check — the gate for cutover step 2 (retiring
Sheets reads).

Usage:
    python scripts/verify_cutover.py [--site SLUG]

Compares the key sets the two stores hold (keywords from
`research_data`+`content_briefs`, article titles from `generated_posts`) and
reports anything present in one but not the other. A clean report (`in_sync:
true`) is the precondition for flipping `STORE_READ_SOURCE=postgres`.

Read-only. Never writes to either store.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Any, Callable, Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.store import drift_report

logger = logging.getLogger(__name__)


def _default_fetch(worksheet_name: str) -> List[Dict[str, Any]]:
    from tools.sheet_tool import manage_sheet_data

    res = manage_sheet_data(worksheet_name=worksheet_name, action="get_all_records")
    if res.get("status") != "success":
        logger.warning(f"fetch '{worksheet_name}' failed: {res.get('message')}")
        return []
    return res.get("data") or []


def verify(fetch_records: Callable[[str], List[Dict[str, Any]]] = _default_fetch,
           site_slug: str = "") -> Dict[str, Any]:
    kw = set()
    for ws in ("research_data", "content_briefs"):
        for rec in fetch_records(ws) or []:
            k = str(rec.get("Keyword/Topic", "")).strip()
            if k:
                kw.add(k)
    titles = {
        str(rec.get("Title", "")).strip()
        for rec in (fetch_records("generated_posts") or [])
        if str(rec.get("Title", "")).strip()
    }
    report = drift_report(kw, titles, site_slug)
    report["in_sync"] = not (
        report["keywords"]["missing_in_postgres"]
        or report["keywords"]["missing_in_sheets"]
        or report["articles"]["missing_in_postgres"]
        or report["articles"]["missing_in_sheets"]
    )
    return report


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Sheets vs Postgres drift check")
    ap.add_argument("--site", default="", help="site slug (default: configured default)")
    args = ap.parse_args()

    report = verify(site_slug=args.site)
    print(json.dumps(report, indent=2))
    if not report["in_sync"]:
        raise SystemExit(2)  # non-zero on drift, so CI/operators notice


if __name__ == "__main__":
    main()
