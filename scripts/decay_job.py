"""Monthly GSC decay job — §5.10-1 (refresh briefs) + §5.16 (ranking write-back).

Usage:
    python scripts/decay_job.py [--dry-run] [--site SLUG]

For every published/ranking article, pull Google Search Console clicks for the
current and prior DECAY_WINDOW_DAYS window; pages with >30% click decay get an
auto-generated refresh brief (major = republish+301 / minor = in-place). The
keyword's ledger status moves to `lost` (rank tracking feedback loop) and an
audit row records the brief so the operator only reviews and runs it.

Pure decision logic lives in `lib/decay.py`; this file is the thin I/O shell
(GSC + DB), with injectable `clicks_fn`/`session` so it is testable offline.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, timedelta
from typing import Any, Callable, Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from sqlalchemy.orm import Session

from lib.db import Article, AuditLog, KeywordLedger, Site, get_session, init_db
from lib.decay import DECAY_WINDOW_DAYS, plan_refresh_briefs

logger = logging.getLogger(__name__)

# GSC data lags ~2-3 days; end the window there, not today.
_GSC_LAG_DAYS = 3


def _clicks_between(page_url: str, start: date, end: date) -> int:
    """Live GSC click total for one page in [start, end]. Imports the client
    lazily so importing this module (and its tests) needs no GSC creds."""
    from lib.search_console import query_search_analytics

    rows = query_search_analytics(
        start_date=start,
        end_date=end,
        row_limit=1,
        dimension_filter_groups=[{
            "filters": [{"dimension": "page", "operator": "equals",
                         "expression": page_url}]
        }],
    )
    return int(rows[0].get("clicks", 0)) if rows else 0


def _windows():
    """(cur_start, cur_end, prior_start, prior_end) — two adjacent equal windows."""
    cur_end = date.today() - timedelta(days=_GSC_LAG_DAYS)
    cur_start = cur_end - timedelta(days=DECAY_WINDOW_DAYS)
    prior_end = cur_start
    prior_start = prior_end - timedelta(days=DECAY_WINDOW_DAYS)
    return cur_start, cur_end, prior_start, prior_end


def collect_pages(session: Session, site: Site,
                  clicks_fn: Callable[[str, date, date], int] = _clicks_between):
    """Per-article decay metrics for a site's published/ranking posts."""
    base = (site.base_url or "").rstrip("/")
    cs, ce, ps, pe = _windows()
    pages = []
    rows = session.execute(
        select(Article).where(
            Article.site_id == site.id,
            Article.status.in_(["published", "ranking"]),
        )
    ).scalars()
    for a in rows:
        url = f"{base}/blog/{a.slug}" if (base and a.slug) else (a.meta or {}).get("url", "")
        if not url:
            continue
        keyword = ""
        if a.keyword_id:
            kr = session.get(KeywordLedger, a.keyword_id)
            keyword = kr.keyword if kr else ""
        pages.append({
            "url": url,
            "title": a.title,
            "keyword": keyword,
            "current_clicks": clicks_fn(url, cs, ce),
            "prior_clicks": clicks_fn(url, ps, pe),
            "article_id": a.id,
            "keyword_id": a.keyword_id,
        })
    return pages


def run(dry_run: bool = False, site_slug: str = "",
        clicks_fn: Callable[[str, date, date], int] = _clicks_between,
        session: Optional[Session] = None) -> Dict[str, Any]:
    """Run the decay scan. Injectable for tests (clicks_fn + session)."""
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
            return {"status": "error", "message": f"site '{site_slug or 'default'}' not found"}

        pages = collect_pages(session, site, clicks_fn)
        briefs = plan_refresh_briefs(pages)
        by_url = {p["url"]: p for p in pages}

        for brief in briefs:
            meta = by_url.get(brief["page_url"], {})
            if dry_run:
                continue
            # §5.16 ranking feedback: decayed keyword → lost (refresh frees it).
            kw_id = meta.get("keyword_id")
            if kw_id:
                row = session.get(KeywordLedger, kw_id)
                if row is not None:
                    row.status = "lost"
            session.add(AuditLog(
                site_id=site.id,
                article_id=meta.get("article_id"),
                action="refresh_brief",
                payload=brief,
            ))
        if briefs and not dry_run:
            session.commit()

        return {
            "status": "ok",
            "site": site.slug,
            "pages_scanned": len(pages),
            "refresh_count": len(briefs),
            "refresh_briefs": briefs,
            "dry_run": dry_run,
        }
    finally:
        if own_session:
            session.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Monthly GSC decay -> refresh briefs job")
    ap.add_argument("--dry-run", action="store_true", help="scan and report only; write nothing")
    ap.add_argument("--site", default="", help="site slug (default: first site)")
    args = ap.parse_args()

    res = run(dry_run=args.dry_run, site_slug=args.site)
    if res.get("status") != "ok":
        print(f"ERROR: {res.get('message')}")
        raise SystemExit(1)
    print(f"[decay_job] site={res['site']} scanned={res['pages_scanned']} "
          f"refresh_briefs={res['refresh_count']} dry_run={res['dry_run']}")
    for b in res["refresh_briefs"]:
        print(f"  - {b['mode']:5} {b['page_url']} (decay={b['decay_pct']}) "
              f"-> {b['actions'][0]}")


if __name__ == "__main__":
    main()
