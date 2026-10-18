"""Backfill Postgres from the existing Google Sheets (Sheets → Postgres cutover).

Usage:
    python scripts/backfill_postgres.py [--dry-run] [--site SLUG]

Content worksheets (the pipeline's own rows):
    research_data, content_briefs, generated_posts, published_posts,
    ContentSpark_Keywords (separate spreadsheet)
each upserted through `lib/store.py` — the same mappers the live dual-write
uses — so a backfill and a live run converge to identical rows.

Historical worksheets (the operator's logs, imported once as history):
    usage logs    -> audit_log action=usage.model   (model performance)
    image_logs    -> cost_ledger kind=image (+ audit usage.image when no
                     article matches the Subject title)
    review        -> audit_log action=article.review
    performance   -> audit_log action=search.performance
    audit         -> audit_log action=article.claims_audit
                     ('claims_audit' is an alias of this same tab — fetched
                     once, never twice)
    freshness_sweep -> audit_log action=article.freshness

Idempotency: keyword/article upserts are keyed on site+keyword / site+title;
historical rows carry a deterministic `sheet_ref` in their payload/detail and
existing refs are preloaded once per action, so a re-run inserts nothing
twice. `approved_unpublished` is a FILTER view of generated_posts —
deliberately not backfilled (it would just re-upsert the same articles).
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Any, Callable, Dict, List, Optional

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from dotenv import load_dotenv

# Load .env BEFORE lib.db can build an engine — without this a direct run
# silently falls back to the legacy sqlite file instead of Postgres.
load_dotenv(os.path.join(REPO_ROOT, ".env"))

from lib.db import get_session, init_db
from lib.store import (
    existing_cost_refs,
    existing_sheet_refs,
    get_or_create_site,
    map_brief_row,
    map_claims_audit_row,
    map_freshness_row,
    map_generated_post_row,
    map_image_log_row,
    map_performance_row,
    map_research_row,
    map_review_row,
    map_usage_log_row,
    mirror_article,
    mirror_brief,
    mirror_keyword,
    mirror_keyword_queue,
    mirror_published_post,
    mirror_sheet_audit,
    mirror_sheet_cost,
    title_article_index,
    verify_cutover,
)

logger = logging.getLogger(__name__)

# Content first (so published_posts matches real articles, not stubs), the
# keyword queue next (additive merge — order-safe either way), then history.
BACKFILL_ORDER = [
    ("research_data", "keyword"),
    ("content_briefs", "brief"),
    ("generated_posts", "article"),
    ("published_posts", "published"),
    ("ContentSpark_Keywords", "keyword_queue"),
    ("usage logs", "usage"),
    ("image_logs", "image"),
    ("review", "review"),
    ("performance", "performance"),
    ("audit", "claims"),
    ("freshness_sweep", "freshness"),
]

# action for each historical-audit worksheet
AUDIT_ACTIONS = {
    "usage": "usage.model",
    "review": "article.review",
    "performance": "search.performance",
    "claims": "article.claims_audit",
    "freshness": "article.freshness",
}

COUNT_KINDS = ["keyword", "brief", "article", "published", "keyword_queue",
               "usage", "image", "review", "performance", "claims",
               "freshness"]


def _default_fetch(worksheet_name: str) -> List[Dict[str, Any]]:
    """Reads a worksheet as records (dict keyed by header). Lazy import so
    tests and dry tooling don't need Sheets creds. ContentSpark_Keywords
    lives in its own spreadsheet, not a tab of ContentSpark."""
    if worksheet_name == "ContentSpark_Keywords":
        try:
            from tools.sheet_tool import get_gspread_client

            return get_gspread_client().open("ContentSpark_Keywords").sheet1 \
                .get_all_records()
        except Exception as e:
            logger.warning(f"fetch 'ContentSpark_Keywords' failed: {e}")
            return []

    from tools.sheet_tool import manage_sheet_data

    res = manage_sheet_data(worksheet_name=worksheet_name, action="get_all_records")
    if res.get("status") != "success":
        logger.warning(f"fetch '{worksheet_name}' failed: {res.get('message')}")
        return []
    return res.get("data") or []


class _HistoryState:
    """Preloaded idempotency sets + the title -> article_id index shared by
    every historical worksheet (one read, not one per row)."""

    def __init__(self, session, site_id: int):
        self.session = session
        self.site_id = site_id
        self.audit_refs: Dict[str, set] = {}
        self.cost_refs: Optional[set] = None
        self.titles = title_article_index(session, site_id)

    def refs_for(self, action: str) -> set:
        if action not in self.audit_refs:
            self.audit_refs[action] = existing_sheet_refs(self.session, action)
        return self.audit_refs[action]

    def image_cost_refs(self) -> set:
        if self.cost_refs is None:
            self.cost_refs = existing_cost_refs(self.session, "image")
        return self.cost_refs


def _handle_audit(kind: str, records: List[Dict[str, Any]], state: _HistoryState,
                  counts: Dict[str, int], dry_run: bool,
                  mapper: Callable[[Dict[str, Any]], Dict[str, Any]]) -> None:
    """One historical worksheet -> audit_log rows (idempotent on sheet_ref)."""
    action = AUDIT_ACTIONS[kind]
    if dry_run:
        counts[kind] += len(records)
        return
    seen = state.refs_for(action)
    for rec in records:
        payload = mapper(rec)
        article_id = state.titles.get(str(payload.get("title") or "").strip())
        if mirror_sheet_audit(state.session, action=action, payload=payload,
                              ts_raw=rec.get("Timestamp"), seen=seen,
                              article_id=article_id, site_id=state.site_id):
            counts[kind] += 1
    state.session.commit()


def _handle_image(records: List[Dict[str, Any]], state: _HistoryState,
                  counts: Dict[str, int], dry_run: bool) -> None:
    """image_logs -> cost_ledger rows attached to the matching article; rows
    whose Subject matches no article keep their history as audit rows."""
    if dry_run:
        counts["image"] += len(records)
        return
    cost_seen = state.image_cost_refs()
    audit_seen = state.refs_for("usage.image")
    for rec in records:
        detail = map_image_log_row(rec)
        subject = str(detail.get("subject") or "").strip()
        article_id = state.titles.get(subject)
        if article_id is not None:
            if mirror_sheet_cost(state.session, kind="image",
                                 amount_usd=float(rec.get("Cost (USD)") or 0),
                                 detail=detail, article_id=article_id,
                                 ts_raw=rec.get("Timestamp"), seen=cost_seen):
                counts["image"] += 1
        elif mirror_sheet_audit(state.session, action="usage.image",
                                payload=detail, ts_raw=rec.get("Timestamp"),
                                seen=audit_seen, site_id=state.site_id):
            counts["image"] += 1
    state.session.commit()


def _handle_published(records: List[Dict[str, Any]], state: _HistoryState,
                      counts: Dict[str, int], dry_run: bool,
                      site_slug: str) -> None:
    """published_posts -> article published URL/slug/status; unknown titles
    become stub published articles (URL inventory for sitemap/decay)."""
    for rec in records:
        if dry_run:
            counts["published"] += 1
            continue
        art, changed = mirror_published_post(
            state.session, title=str(rec.get("Keyword/Topic") or ""),
            url=str(rec.get("Post URL") or ""), site_slug=site_slug)
        if changed:
            counts["published"] += 1
        if art is not None:
            # keep the shared title index warm for later worksheets
            state.titles.setdefault(str(rec.get("Keyword/Topic") or "").strip(),
                                    art.id)
    if not dry_run:
        state.session.commit()


def backfill(fetch_records: Callable[[str], List[Dict[str, Any]]] = _default_fetch,
             dry_run: bool = False, site_slug: str = "") -> Dict[str, Any]:
    init_db()
    session = get_session()
    counts: Dict[str, int] = {k: 0 for k in COUNT_KINDS}
    try:
        site_id: Optional[int] = None
        state: Optional[_HistoryState] = None
        if not dry_run:
            site_id = get_or_create_site(session, site_slug).id

        for worksheet, kind in BACKFILL_ORDER:
            records = fetch_records(worksheet) or []
            if kind in ("keyword", "brief", "article"):
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
                    else:
                        mirror_article(session, site_slug=site_slug,
                                       **map_generated_post_row(row, headers))
                    counts[kind] += 1
                if not dry_run:
                    session.commit()
                    if kind == "article":
                        # build the shared title index AFTER generated_posts so
                        # articles created this run are findable by the
                        # historical worksheets' title lookups
                        state = _HistoryState(session, site_id)
            elif kind == "published":
                _handle_published(records, state, counts, dry_run, site_slug)
            elif kind == "keyword_queue":
                if dry_run:
                    counts[kind] += len(records)
                    continue
                for rec in records:
                    _row, changed = mirror_keyword_queue(
                        session,
                        keyword=str(rec.get("Keyword") or ""),
                        primary=str(rec.get("Primary Keyword") or ""),
                        secondary=str(rec.get("Secondary Keywords") or ""),
                        status=str(rec.get("Status") or ""),
                        site_slug=site_slug)
                    if changed:
                        counts[kind] += 1
                session.commit()
            elif kind == "image":
                _handle_image(records, state, counts, dry_run)
            else:
                _handle_audit(kind, records, state, counts, dry_run,
                              {"usage": map_usage_log_row,
                               "review": map_review_row,
                               "performance": map_performance_row,
                               "claims": map_claims_audit_row,
                               "freshness": map_freshness_row}[kind])

        verify = None
        if not dry_run:
            verify = verify_cutover(session, site_slug)
        return {"status": "ok", "counts": counts, "verify": verify,
                "dry_run": dry_run}
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
