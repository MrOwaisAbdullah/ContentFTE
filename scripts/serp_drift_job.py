"""Monthly SERP drift scan — spec §5.16 "SERP snapshots & drift alerts".

Usage:
    python scripts/serp_drift_job.py [--dry-run] [--site SLUG] [--limit N]

For each cached keyword SERP baseline (SeoCache row for the active
provider), force-refresh the live top-10 and compare it against the
brief-time baseline: when <40% of the baseline URLs are still present
(`lib.serp_drift.detect_drift`), the results shifted — the job writes a
`serp.drift` audit row and bumps the keyword's `review_at` so the
operator re-briefs/refreshes the page. The refreshed payload replaces
the cache, becoming the baseline for the next run.

SEO_DATA_PROVIDER=off (default) has no live SERP to fetch — the job
skips deterministically. Pure logic lives in `lib/serp_drift.py`; this
file is the thin I/O shell (provider + DB), with injectable
`fetch_fn`/`session` so it is testable offline.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from sqlalchemy.orm import Session

from lib.db import AuditLog, KeywordLedger, SeoCache, Site, get_session, init_db
from lib.seo_provider import get_keyword_data, provider_name
from lib.serp_drift import detect_drift, serp_urls

logger = logging.getLogger(__name__)

# Bound provider spend per run (monthly job; raise via --limit if wanted).
DEFAULT_LIMIT = 50


def _baseline_urls(session: Session, provider: str, keyword: str) -> list[str]:
    """Brief-time top-N from the raw cache row — deliberately ignores the
    30-day cache age: the baseline is a snapshot, not a live read."""
    row = session.execute(
        select(SeoCache).where(SeoCache.provider == provider,
                               SeoCache.keyword == keyword)
    ).scalar_one_or_none()
    if row is None:
        return []
    return serp_urls((row.data or {}).get("serp"))


def run(dry_run: bool = False, site_slug: str = "", limit: int = DEFAULT_LIMIT,
        fetch_fn: Optional[Callable[[str], Dict[str, Any]]] = None,
        session: Optional[Session] = None) -> Dict[str, Any]:
    """Run the drift scan. Injectable for tests (fetch_fn + session)."""
    provider = provider_name()
    if provider == "off":
        return {"status": "skipped",
                "message": "SEO_DATA_PROVIDER=off — no live SERP to compare"}

    own_session = session is None
    if own_session:
        init_db()
        session = get_session()
    try:
        if site_slug:
            site = session.execute(
                select(Site).where(Site.slug == site_slug)
            ).scalar_one_or_none()
        else:
            site = session.execute(
                select(Site).order_by(Site.id.asc())
            ).scalars().first()
        if site is None:
            return {"status": "error",
                    "message": f"site '{site_slug or 'default'}' not found"}

        rows = session.execute(
            select(SeoCache).where(SeoCache.provider == provider)
            .order_by(SeoCache.id.asc()).limit(max(1, int(limit)))
        ).scalars().all()

        checked = 0
        no_baseline = 0
        fetch_errors = 0
        no_fresh = 0
        drifted: list[dict] = []
        now = datetime.now(timezone.utc)
        for row in rows:
            baseline = _baseline_urls(session, provider, row.keyword)
            if not baseline:
                no_baseline += 1
                continue
            checked += 1
            try:
                if fetch_fn is not None:
                    fresh_data = fetch_fn(row.keyword)
                else:
                    fresh_data = get_keyword_data(
                        session, row.keyword, force_refresh=True)
            except Exception as exc:  # provider outage: per-keyword, fail-open
                fetch_errors += 1
                logger.warning("serp_drift: fetch failed for %r: %s",
                               row.keyword, exc)
                continue
            fresh = serp_urls(
                (fresh_data or {}).get("serp")
                if isinstance(fresh_data, dict) else None)
            if not fresh:
                no_fresh += 1
                continue
            report = detect_drift(baseline, fresh)
            report["keyword"] = row.keyword
            report["provider"] = provider
            if not report["drifted"]:
                continue
            drifted.append(report)
            if dry_run:
                continue
            ledger = session.execute(
                select(KeywordLedger)
                .where(KeywordLedger.site_id == site.id,
                       KeywordLedger.keyword == row.keyword)
            ).scalars().first()
            if ledger is not None:
                # review queue (lib.ledger due-review query) picks it up.
                ledger.review_at = now
            session.add(AuditLog(site_id=site.id, action="serp.drift",
                                 payload=report))
        if not dry_run:
            session.commit()

        return {
            "status": "ok",
            "site": site.slug,
            "provider": provider,
            "candidates": len(rows),
            "checked": checked,
            "drift_count": len(drifted),
            "drifted": drifted,
            "fetch_errors": fetch_errors,
            "no_baseline": no_baseline,
            "no_fresh": no_fresh,
            "dry_run": dry_run,
        }
    finally:
        if own_session:
            session.close()


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(
        description="Monthly SERP drift scan -> audit + review flags (5.16)")
    ap.add_argument("--dry-run", action="store_true",
                    help="compare and report only; write nothing")
    ap.add_argument("--site", default="", help="site slug (default: first site)")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                    help=f"max cached keywords to check (default {DEFAULT_LIMIT})")
    args = ap.parse_args()

    res = run(dry_run=args.dry_run, site_slug=args.site, limit=args.limit)
    if res.get("status") == "skipped":
        print(f"[serp_drift] skipped: {res['message']}")
        return 0
    if res.get("status") != "ok":
        print(f"ERROR: {res.get('message')}")
        return 1
    print(f"[serp_drift] site={res['site']} provider={res['provider']} "
          f"checked={res['checked']} drift={res['drift_count']} "
          f"fetch_errors={res['fetch_errors']} dry_run={res['dry_run']}")
    for d in res["drifted"]:
        print(f"  - {d['keyword']}: overlap={d['overlap_score']} "
              f"dropped={len(d['dropped'])} new={len(d['new'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
