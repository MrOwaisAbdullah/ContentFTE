"""§5.16 / §5.14 Sheets → Postgres dual-write mirror + backfill.

Runs against a throwaway sqlite DB; Sheets access is injected, never called.
"""
import importlib.util
import os

import pytest
from sqlalchemy import func, select

from lib import store

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_backfill():
    path = os.path.join(REPO_ROOT, "scripts", "backfill_postgres.py")
    spec = importlib.util.spec_from_file_location("backfill_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def temp_db(tmp_path):
    import lib.db as db
    old_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path / 'store_test.db'}"
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


# ---------------------------------------------------------------------------
# Row mappers
# ---------------------------------------------------------------------------
def test_map_research_row_positional_and_headers():
    row = ["ai agents", "1,200", "45.5", "informational", "sum", "u", "t", "Yes"]
    m = store.map_research_row(row)
    assert m["keyword"] == "ai agents"
    assert m["volume"] == 1200
    assert m["difficulty"] == 45.5
    assert m["generated"] is True
    # header-keyed mapping is order-independent
    m2 = store.map_research_row(row, headers=store._RESEARCH_HEADERS)
    assert m2 == m


def test_map_generated_post_row_flags():
    row = ["Title A", "# body", "[]", "92.5", "sum", "Approved", "No"]
    m = store.map_generated_post_row(row)
    assert m["title"] == "Title A"
    assert m["quality_score"] == 92.5
    assert m["approved"] is True
    assert m["published"] is False
    row2 = ["Title B", "body", "[]", "", "s", "Approved", "Yes"]
    assert store.map_generated_post_row(row2)["published"] is True


def test_map_brief_row():
    row = ["kw", "brief body", '[{"q":1}]', "https://x", "sum", "Yes"]
    m = store.map_brief_row(row)
    assert m["keyword"] == "kw"
    assert m["brief_content"] == "brief body"
    assert m["generated"] is True


# ---------------------------------------------------------------------------
# Upserts
# ---------------------------------------------------------------------------
def test_mirror_keyword_idempotent_and_status(temp_db):
    s = temp_db.get_session()
    try:
        store.mirror_keyword(s, keyword="kw a", volume=100, difficulty=20, intent="commercial")
        store.mirror_keyword(s, keyword="kw a", volume=150, difficulty=25, intent="commercial",
                             generated=True)
        rows = list(s.execute(select(temp_db.KeywordLedger)).scalars())
        assert len(rows) == 1
        assert rows[0].volume == 150
        assert rows[0].status == "briefed"  # Generated=Yes
    finally:
        s.close()


def test_mirror_brief_stores_snapshot(temp_db):
    s = temp_db.get_session()
    try:
        row = store.mirror_brief(s, keyword="kw b", brief_content="B", faqs="[]",
                                 sources="u", generated=True)
        assert row.status == "briefed"
        assert row.research_snapshot["brief"] == "B"
    finally:
        s.close()


def test_mirror_article_upsert_and_status(temp_db):
    s = temp_db.get_session()
    try:
        store.mirror_article(s, title="Post A", content="v1", quality_score=80,
                             approved=True, published=False)
        store.mirror_article(s, title="Post A", content="v2", quality_score=95,
                             approved=True, published=True)
        arts = list(s.execute(select(temp_db.Article)).scalars())
        assert len(arts) == 1
        assert arts[0].content_md == "v2"
        assert arts[0].status == "published"
        assert arts[0].scores["quality"] == 95
    finally:
        s.close()


# ---------------------------------------------------------------------------
# The dual-write hook
# ---------------------------------------------------------------------------
def test_mirror_sheet_append_dispatch(temp_db):
    assert store.mirror_sheet_append(
        "generated_posts", ["Title X", "body", "[]", "88", "s", "Approved", "No"]) is True
    assert store.mirror_sheet_append(
        "research_data", ["kw c", "10", "5", "informational", "s", "u", "t", "No"]) is True
    assert store.mirror_sheet_append("unknown_sheet", ["a"]) is False
    s = temp_db.get_session()
    try:
        assert s.execute(select(func.count()).select_from(temp_db.Article)).scalar_one() == 1
        assert s.execute(select(func.count()).select_from(temp_db.KeywordLedger)).scalar_one() == 1
    finally:
        s.close()


def test_mirror_disabled_flag(temp_db, monkeypatch):
    monkeypatch.setattr(store, "DUALWRITE_ENABLED", False)
    assert store.mirror_sheet_append(
        "generated_posts", ["T", "b", "[]", "1", "s", "Approved", "No"]) is False


def test_verify_cutover_counts(temp_db):
    s = temp_db.get_session()
    try:
        store.mirror_keyword(s, keyword="k1", site_slug="t")
        store.mirror_article(s, title="a1", site_slug="t")
        store.mirror_article(s, title="a2", site_slug="t")
        v = store.verify_cutover(s, "t")
        assert v == {"site": "t", "keywords": 1, "articles": 2}
    finally:
        s.close()


# ---------------------------------------------------------------------------
# Backfill
# ---------------------------------------------------------------------------
def _fake_records(worksheet):
    return {
        "research_data": [
            {"Keyword/Topic": "k1", "Search Volume": "10", "Difficulty": "5",
             "User Intent": "informational", "Content Summary": "s",
             "Source URLs": "", "Source Titles": "", "Generated": "Yes"},
            {"Keyword/Topic": "k2", "Search Volume": "20", "Difficulty": "7",
             "User Intent": "commercial", "Content Summary": "s",
             "Source URLs": "", "Source Titles": "", "Generated": "No"},
        ],
        "content_briefs": [
            {"Keyword/Topic": "k1", "Brief Content": "B", "FAQs": "[]",
             "External Source Links": "u", "Content Summary": "s", "Generated": "Yes"},
        ],
        "generated_posts": [
            {"Title": "P1", "Generated Content": "body", "FAQs": "[]",
             "Quality Score": "91", "Summary": "s",
             "Approve/Disapprove": "Approved", "Published": "Yes"},
        ],
    }.get(worksheet, [])


def test_backfill_counts_verify_and_idempotency(temp_db):
    job = _load_backfill()
    res = job.backfill(fetch_records=_fake_records, site_slug="t")
    assert res["status"] == "ok"
    assert res["counts"] == {"keyword": 2, "brief": 1, "article": 1}
    assert res["verify"] == {"site": "t", "keywords": 2, "articles": 1}

    # Re-run is a no-op (idempotent keyed upserts).
    res2 = job.backfill(fetch_records=_fake_records, site_slug="t")
    assert res2["verify"] == {"site": "t", "keywords": 2, "articles": 1}


def test_backfill_dry_run_writes_nothing(temp_db):
    job = _load_backfill()
    res = job.backfill(fetch_records=_fake_records, dry_run=True, site_slug="t")
    assert res["counts"] == {"keyword": 2, "brief": 1, "article": 1}
    assert res["verify"] is None
    s = temp_db.get_session()
    try:
        assert s.execute(select(func.count()).select_from(temp_db.Article)).scalar_one() == 0
        assert s.execute(select(func.count()).select_from(temp_db.KeywordLedger)).scalar_one() == 0
    finally:
        s.close()


def test_sheet_tool_append_hooks_mirror():
    src = open(os.path.join(REPO_ROOT, "tools", "sheet_tool.py"), encoding="utf-8").read()
    assert "mirror_sheet_append" in src
