"""Extended backfill — the historical worksheets beyond research/briefs/posts.

published_posts, usage logs, image_logs, review, performance, audit (the
claims tab), freshness_sweep and the separate ContentSpark_Keywords queue.
Throwaway sqlite DB; every sheet access injected, never called.
"""
from __future__ import annotations

import importlib.util
import os
from datetime import timezone

import pytest
from sqlalchemy import func, select

from lib import store

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_backfill():
    path = os.path.join(REPO_ROOT, "scripts", "backfill_postgres.py")
    spec = importlib.util.spec_from_file_location("backfill_history_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def temp_db(tmp_path):
    import lib.db as db
    old_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path / 'history_test.db'}"
    db._engine = None
    db._SessionLocal = None
    db.init_db()
    yield db
    if db._engine is not None:
        db._engine.dispose()
    db._engine = None
    db._SessionLocal = None
    if old_url is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = old_url


# Injected records for every worksheet the extended backfill reads.
FAKE = {
    "research_data": [],
    "content_briefs": [],
    "generated_posts": [],
    "published_posts": [
        {"Keyword/Topic": "Alpha Post",
         "Post URL": "https://owaisabdullah.dev/blog/alpha-post/",
         "Error": ""},
        # older post with no article row -> stub published article
        {"Keyword/Topic": "Ancient Post",
         "Post URL": "https://owaisabdullah.dev/blog/ancient-post/",
         "Error": ""},
        # publish failed: no URL -> skipped entirely
        {"Keyword/Topic": "Broken Row", "Post URL": "", "Error": "timeout"},
    ],
    "ContentSpark_Keywords": [
        {"Keyword": "alpha post", "Primary Keyword": "alpha kw",
         "Secondary Keywords": "beta, gamma", "Status": "available"},
        # pre-existing ledger row: status must be kept, snapshot merged
        {"Keyword": "existing kw", "Primary Keyword": "p",
         "Secondary Keywords": "s", "Status": "claimed"},
        {"Keyword": "", "Primary Keyword": "", "Secondary Keywords": "",
         "Status": "available"},  # blank keyword -> skipped
    ],
    "usage logs": [
        {"Timestamp": "2026-10-18 07:54:33 UTC", "Model": "gemini-3.1-flash-lite",
         "Agent": "Output Agent", "Stage": "output", "Status": "success",
         "Latency (s)": "5.1"},
        # exact duplicate row -> same sheet_ref, deduped within the run
        {"Timestamp": "2026-10-18 07:54:33 UTC", "Model": "gemini-3.1-flash-lite",
         "Agent": "Output Agent", "Stage": "output", "Status": "success",
         "Latency (s)": "5.1"},
        {"Timestamp": "2026-10-17 09:00:00 UTC", "Model": "gemini-3-pro",
         "Agent": "Research Agent", "Stage": "research", "Status": "success",
         "Latency (s)": "12.3"},
    ],
    "image_logs": [
        {"Timestamp": "2026-10-18 11:59:42 UTC", "Model": "flux",
         "Stage": "result", "Subject": "Alpha Post", "Status": "passed",
         "Reference": "", "Latency (s)": "40.6", "Detail": "attempts=1",
         "Cost (USD)": "0.0012", "Slot": "featured", "Latency (ms)": "40572",
         "Prompt": ""},
        # no article matches the Subject -> audit usage.image, not cost
        {"Timestamp": "2026-10-17 10:00:00 UTC", "Model": "flux",
         "Stage": "result", "Subject": "Unknown Subject", "Status": "failed",
         "Reference": "", "Latency ( s)": "", "Latency (s)": "5.0",
         "Detail": "err", "Cost (USD)": "0.0005", "Slot": "featured",
         "Latency (ms)": "5000", "Prompt": ""},
    ],
    "review": [
        {"Timestamp": "2026-10-13 11:01 UTC", "Status": "REJECTED_TOPIC",
         "Title": "Alpha Post", "Quality Score": "40", "Summary": "thin",
         "Reason": "off-brief"},
    ],
    "performance": [
        {"Timestamp": "2026-10-12 09:00 UTC", "Title": "Alpha Post",
         "URL": "https://owaisabdullah.dev/blog/alpha-post/",
         "Impressions": "120", "Clicks": "4", "CTR": "3.3%",
         "Average Position": "8.2", "Finding": "f", "Suggested Edit": "e",
         "Status": "open"},
    ],
    "audit": [
        {"Title": "Alpha Post", "Keyword/Topic": "alpha",
         "Quality Score": "70", "Claims Notes": "2 unverified",
         "Timestamp": "2026-10-11 10:00 UTC"},
    ],
    "freshness_sweep": [
        {"Timestamp": "2026-10-10 10:00 UTC", "Title": "Alpha Post",
         "Status": "stale", "Reason": "old stats",
         "Suggested Edit": "refresh"},
    ],
}


def _seed(site_slug: str = "t") -> int:
    """Pre-existing world: one site, one real article, one rich keyword."""
    from lib.db import Article, get_session
    from lib.ledger import upsert_keyword
    from lib.store import get_or_create_site

    s = get_session()
    try:
        site = get_or_create_site(s, site_slug)
        art = Article(site_id=site.id, title="Alpha Post", slug="alpha",
                      status="approved", content_md="body")
        s.add(art)
        kw = upsert_keyword(s, site.id, "existing kw",
                            research_snapshot={"summary": "rich"})
        kw.research_snapshot = {"summary": "rich"}
        s.commit()
        return art.id
    finally:
        s.close()


def _fetch(name):
    return FAKE.get(name, [])


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------
def test_sheet_ts_formats_and_garbage():
    a = store._sheet_ts("2026-10-18 07:54:33 UTC")
    assert a.year == 2026 and a.tzinfo == timezone.utc and a.second == 33
    b = store._sheet_ts("2026-10-13 11:01 UTC")  # older rows: no seconds
    assert b.minute == 1 and b.second == 0
    assert store._sheet_ts("not a date") is None
    assert store._sheet_ts("") is None


# ---------------------------------------------------------------------------
# Mirrors (idempotency without the backfill's preloaded sets)
# ---------------------------------------------------------------------------
def test_mirror_sheet_audit_fallback_query_dedupes(temp_db):
    s = temp_db.get_session()
    try:
        payload = {"sheet_ref": "review:T|X", "title": "X"}
        assert store.mirror_sheet_audit(s, action="article.review",
                                        payload=payload, ts_raw="2026-10-13 11:01 UTC") is True
        # no `seen` set -> falls back to a query, still no duplicate
        assert store.mirror_sheet_audit(s, action="article.review",
                                        payload=dict(payload)) is False
        s.commit()
        n = s.execute(select(func.count()).select_from(
            temp_db.AuditLog)).scalar_one()
        assert n == 1
        row = s.execute(select(temp_db.AuditLog)).scalars().one()
        assert row.created_at.year == 2026  # historical timestamp kept
    finally:
        s.close()


def test_mirror_sheet_cost_fallback_query_dedupes(temp_db):
    s = temp_db.get_session()
    try:
        from lib.db import Article, get_session  # noqa: F401
        site = store.get_or_create_site(s, "t")
        art = Article(site_id=site.id, title="T", slug="t")
        s.add(art)
        s.commit()
        detail = {"sheet_ref": "image:T|M|s", "subject": "T"}
        assert store.mirror_sheet_cost(s, kind="image", amount_usd=0.5,
                                       detail=detail, article_id=art.id,
                                       ts_raw="2026-10-18 11:59:42 UTC") is True
        assert store.mirror_sheet_cost(s, kind="image", amount_usd=0.5,
                                       detail=dict(detail),
                                       article_id=art.id) is False
        s.commit()
        assert store.existing_cost_refs(s, "image") == {"image:T|M|s"}
    finally:
        s.close()


def test_mirror_published_post_match_stub_and_recount(temp_db):
    s = temp_db.get_session()
    try:
        site = store.get_or_create_site(s, "t")
        art = temp_db.Article(site_id=site.id, title="Matched",
                              slug="old", status="approved")
        s.add(art)
        s.commit()
        matched, changed = store.mirror_published_post(
            s, title="Matched",
            url="https://x.dev/blog/new-slug/", site_slug="t")
        assert changed is True and matched.status == "published"
        assert matched.meta["published_url"] == "https://x.dev/blog/new-slug/"
        # slug already set -> kept (stable URLs, no re-slug)
        assert matched.slug == "old"
        # second pass: nothing changes
        same, changed2 = store.mirror_published_post(
            s, title="Matched", url="https://x.dev/blog/new-slug/",
            site_slug="t")
        assert same.id == matched.id and changed2 is False
        # unknown title -> stub carries the URL
        stub, changed3 = store.mirror_published_post(
            s, title="Ghost", url="https://x.dev/blog/ghost/", site_slug="t")
        assert changed3 is True and stub.status == "published"
        assert stub.slug == "ghost"
        # no URL (failed publish) -> skipped
        assert store.mirror_published_post(s, title="Ghost", url="",
                                           site_slug="t") == (None, False)
    finally:
        s.close()


def test_mirror_keyword_queue_create_merge_and_blank(temp_db):
    s = temp_db.get_session()
    try:
        site = store.get_or_create_site(s, "t")
        kw = store.upsert_keyword(s, site.id, "rich kw",
                                  research_snapshot={"summary": "keep"})
        kw.status = "briefed"
        s.commit()
        # blank keyword -> skipped
        assert store.mirror_keyword_queue(s, keyword="  ") == (None, False)
        # existing row: status untouched, snapshot only gains missing keys
        row, merged = store.mirror_keyword_queue(
            s, keyword="rich kw", primary="P", secondary="S",
            status="available", site_slug="t")
        assert merged is True
        assert row.status == "briefed"  # claim state never clobbers
        assert row.research_snapshot == {"summary": "keep",
                                         "primary_keyword": "P",
                                         "secondary_keywords": "S"}
        # merge is one-shot: a second pass changes nothing
        _row, merged2 = store.mirror_keyword_queue(
            s, keyword="rich kw", primary="P", secondary="S", site_slug="t")
        assert merged2 is False
        # new row: sheet status maps to the ledger vocabulary
        fresh, created = store.mirror_keyword_queue(
            s, keyword="fresh kw", status="available", site_slug="t")
        assert created is True and fresh.status == "queued"
        assert fresh.research_snapshot["source"] == "keywords-sheet"
    finally:
        s.close()


# ---------------------------------------------------------------------------
# The whole extended backfill, twice (idempotency is the contract)
# ---------------------------------------------------------------------------
def test_extended_backfill_counts_links_and_idempotency(temp_db):
    alpha_id = _seed()
    job = _load_backfill()

    res = job.backfill(fetch_records=_fetch, site_slug="t")
    assert res["status"] == "ok"
    assert res["counts"] == {
        "keyword": 0, "brief": 0, "article": 0,
        "published": 2,       # Alpha matched + Ancient stub; Broken skipped
        "keyword_queue": 2,   # alpha post created + existing kw merged
        "usage": 2,           # duplicate row collapsed by sheet_ref
        "image": 2,           # 1 cost (article match) + 1 audit fallback
        "review": 1, "performance": 1, "claims": 1, "freshness": 1,
    }

    s = temp_db.get_session()
    try:
        # published_posts enriched the real article + created the stub
        alpha = s.execute(select(temp_db.Article).where(
            temp_db.Article.title == "Alpha Post")).scalars().one()
        assert alpha.status == "published"
        assert alpha.meta["published_url"] == \
            "https://owaisabdullah.dev/blog/alpha-post/"
        stub = s.execute(select(temp_db.Article).where(
            temp_db.Article.title == "Ancient Post")).scalars().one()
        assert stub.status == "published" and stub.slug == "ancient-post"
        assert s.execute(select(temp_db.Article).where(
            temp_db.Article.title == "Broken Row")).scalars().first() is None

        # audit rows, article-linked where a title match exists
        def n(action):
            return s.execute(select(func.count()).select_from(
                temp_db.AuditLog).where(temp_db.AuditLog.action == action)
            ).scalar_one()

        assert n("usage.model") == 2
        assert n("usage.image") == 1
        assert n("article.review") == 1
        assert n("search.performance") == 1
        assert n("article.claims_audit") == 1
        assert n("article.freshness") == 1
        review = s.execute(select(temp_db.AuditLog).where(
            temp_db.AuditLog.action == "article.review")).scalars().one()
        assert review.article_id == alpha_id  # linked by title
        assert review.site_id is not None
        perf = s.execute(select(temp_db.AuditLog).where(
            temp_db.AuditLog.action == "search.performance")).scalars().one()
        assert perf.created_at.year == 2026  # historical timestamp

        # image_logs: cost attaches to the matched article
        costs = list(s.execute(select(temp_db.CostLedger).where(
            temp_db.CostLedger.kind == "image")).scalars())
        assert len(costs) == 1
        assert costs[0].amount_usd == pytest.approx(0.0012)
        assert costs[0].article_id == alpha_id
        assert costs[0].detail["subject"] == "Alpha Post"

        # keyword queue: new row mapped, existing row preserved
        kws = {(k.keyword, k.status) for k in s.execute(
            select(temp_db.KeywordLedger)).scalars()}
        assert ("alpha post", "queued") in kws
        assert ("existing kw", "researched") in kws
        rich = s.execute(select(temp_db.KeywordLedger).where(
            temp_db.KeywordLedger.keyword == "existing kw")).scalars().one()
        assert rich.research_snapshot["summary"] == "rich"
        assert rich.research_snapshot["primary_keyword"] == "p"
    finally:
        s.close()

    # Re-run: every historical kind reports zero; nothing duplicated.
    res2 = job.backfill(fetch_records=_fetch, site_slug="t")
    assert all(v == 0 for v in res2["counts"].values()), res2["counts"]
    s = temp_db.get_session()
    try:
        total_audit = s.execute(select(func.count()).select_from(
            temp_db.AuditLog)).scalar_one()
        # usage 2 + usage.image 1 + review + performance + claims + freshness
        assert total_audit == 7
        total_articles = s.execute(select(func.count()).select_from(
            temp_db.Article)).scalar_one()
        assert total_articles == 2
        total_costs = s.execute(select(func.count()).select_from(
            temp_db.CostLedger)).scalar_one()
        assert total_costs == 1
        total_kw = s.execute(select(func.count()).select_from(
            temp_db.KeywordLedger)).scalar_one()
        assert total_kw == 2
    finally:
        s.close()


def test_extended_backfill_dry_run_writes_nothing(temp_db):
    _seed()
    job = _load_backfill()
    res = job.backfill(fetch_records=_fetch, dry_run=True, site_slug="t")
    assert res["counts"]["published"] == 3
    assert res["counts"]["usage"] == 3
    assert res["counts"]["image"] == 2
    assert res["verify"] is None
    s = temp_db.get_session()
    try:
        assert s.execute(select(func.count()).select_from(
            temp_db.AuditLog)).scalar_one() == 0
        assert s.execute(select(func.count()).select_from(
            temp_db.CostLedger)).scalar_one() == 0
        # _seed rows only
        assert s.execute(select(func.count()).select_from(
            temp_db.Article)).scalar_one() == 1
    finally:
        s.close()
