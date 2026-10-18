"""Spec 3a/3b — the worksheet choke point in Postgres mode.

With SHEETS_ENABLED=0 (site #2) or STORE_READ_SOURCE=postgres (site #1
post-flip) manage_sheet_data serves the three mapped worksheets from
derived Postgres views instead of gspread: reads are rebuilt in append
order (row_index = position + 2) and writes map header -> field on the
ledger/article row. Unmapped worksheets become no-op successes so stage
code never sees an auth error.
"""
import pytest


@pytest.fixture
def pg_db(tmp_path, monkeypatch):
    import lib.db as db

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'choke.db'}")
    monkeypatch.setenv("SHEETS_ENABLED", "0")
    monkeypatch.delenv("STORE_READ_SOURCE", raising=False)
    db._engine = None
    db._SessionLocal = None
    db.init_db()

    from tools import sheet_tool

    sheet_tool.clear_keyword_claim()
    sheet_tool._reset_gspread_cache()

    def _boom(*a, **k):  # pragma: no cover - a hit here is the bug
        raise AssertionError("gspread client touched while Sheets is disabled")

    monkeypatch.setattr(sheet_tool, "get_gspread_client", _boom)
    yield db
    sheet_tool.clear_keyword_claim()
    if db._engine is not None:
        db._engine.dispose()
    db._engine = None
    db._SessionLocal = None


def _site():
    from lib import store
    from lib.db import get_session

    s = get_session()
    try:
        return store.get_or_create_site(s, store.DEFAULT_SITE_SLUG)
    finally:
        s.close()


def _manage(ws, action, **kw):
    from tools import sheet_tool

    return sheet_tool.manage_sheet_data(worksheet_name=ws, action=action, **kw)


# ---------------------------------------------------------------------------
# Read side: derived views, header contract, row addressing
# ---------------------------------------------------------------------------
def test_mapped_headers_match_the_stage_contract(pg_db):
    from tools.sheet_tool import _pg_headers_for

    assert _pg_headers_for("research_data") == [
        "Keyword/Topic", "Search Volume", "Difficulty", "User Intent",
        "Content Summary", "Source URLs", "Source Titles", "Generated",
        "Primary Keyword", "Secondary Keywords", "Created At",
    ]
    assert _pg_headers_for("content_briefs") == [
        "Keyword/Topic", "Brief Content", "FAQs", "External Source Links",
        "Content Summary", "Generated", "Secondary Keywords", "Created At",
    ]

    # generated_posts must line up with the stage's positional append, or a
    # header-based repair would write to the wrong column.
    import scripts.run_stage as rs

    posts = _pg_headers_for("generated_posts")
    assert posts[:10] == rs._GENERATED_POSTS_FIELDS
    assert posts[10:] == ["Created At", "Image Source",
                          "Last Freshness Check", "Last Performance Check"]


def test_research_view_and_row_addressing(pg_db):
    _site()
    appended = _manage("research_data", "append_row", row_values=[
        "topic alpha", "1000", "22.5", "informational", "a summary",
        "https://a", "Src A", "No", "primary a", "sec a",
        "2026-01-02 03:04:05 UTC",
    ])
    assert appended["status"] == "success"
    assert appended["message"] == "Row appended to research_data."

    records = _manage("research_data", action="get_all_records")
    assert records["status"] == "success" and records["count"] == 1
    row = records["data"][0]
    assert row["Keyword/Topic"] == "topic alpha"
    assert row["Search Volume"] == 1000
    assert row["Difficulty"] == 22.5
    assert row["Generated"] == "No"
    # trailing sheet-only columns survive the trip through the JSON snapshot
    assert row["Source URLs"] == "https://a"
    assert row["Created At"] == "2026-01-02 03:04:05 UTC"

    # row 1 is the header row; data starts at row 2
    header = _manage("research_data", action="get_row", row_index=1)
    assert header["data"][0] == "Keyword/Topic"
    data_row = _manage("research_data", action="get_row", row_index=2)
    assert data_row["data"][0] == "topic alpha"
    col = _manage("research_data", action="get_column", col_index=1)
    assert col["data"][0] == "Keyword/Topic" and col["data"][1] == "topic alpha"
    rng = _manage("research_data", action="get_range", cell_range="1:1")
    assert rng["data"][0][:3] == ["Keyword/Topic", "Search Volume", "Difficulty"]
    block = _manage("research_data", action="get_range", cell_range="A2:B3")
    assert block["data"] == [["topic alpha", 1000]]

    sheet_info = _manage("research_data", action="get_worksheet")
    assert sheet_info["row_count"] == 2 and sheet_info["col_count"] == 11

    found = _manage("research_data", action="find_row_by_key",
                    key_column="Keyword/Topic", key_value="topic alpha")
    assert found["found"] is True and found["row_index"] == 2
    # the ledger keyword (primary) matches the same row too
    by_primary = _manage("research_data", action="find_row_by_key",
                         key_column="Keyword/Topic", key_value="primary a")
    assert by_primary["found"] is True and by_primary["row_index"] == 2
    missing = _manage("research_data", action="find_row_by_key",
                      key_column="Keyword/Topic", key_value="nope")
    assert missing["found"] is False and missing["row_index"] is None


def test_brief_append_drives_research_generated_flag(pg_db):
    _site()
    _manage("research_data", "append_row", row_values=[
        "topic beta", "10", "5", "commercial", "research summary",
        "u", "t", "No", "primary b", "", "2026-02-01 00:00:00 UTC",
    ])
    _manage("content_briefs", "append_row", row_values=[
        "topic beta", "# Brief", '["q"]', "https://src", "brief summary",
        "No", "secondary b",
    ])

    research = _manage("research_data", action="get_all_records")
    assert research["data"][0]["Generated"] == "Yes"
    briefs = _manage("content_briefs", action="get_all_records")
    assert briefs["count"] == 1
    brief = briefs["data"][0]
    assert brief["Brief Content"] == "# Brief"
    assert brief["Generated"] == "No"
    assert brief["External Source Links"] == "https://src"

    # a later research append for the same keyword must NOT wipe the brief
    # (lib.store's mirror replaces the snapshot wholesale; we merge it back)
    _manage("research_data", "append_row", row_values=[
        "topic beta", "11", "6", "commercial", "research summary v2",
        "u", "t", "No", "primary b", "", "",
    ])
    briefs_after = _manage("content_briefs", action="get_all_records")
    assert briefs_after["count"] == 1
    assert briefs_after["data"][0]["Brief Content"] == "# Brief"
    research_after = _manage("research_data", action="get_all_records")
    assert research_after["data"][0]["Content Summary"] == "research summary v2"
    assert research_after["data"][0]["Generated"] == "Yes"


def test_delete_content_brief_marks_generated_instead_of_removing(pg_db):
    _site()
    _manage("content_briefs", "append_row", row_values=[
        "topic gamma", "brief", "", "", "", "No", ""])

    claimable = _manage("content_briefs", action="find_row_by_key",
                        key_column="Generated", key_value="No")
    assert claimable["found"] is True and claimable["row_index"] == 2

    deleted = _manage("content_briefs", action="delete_row",
                      row_index=claimable["row_index"])
    assert deleted["status"] == "success"

    # the brief row is retained (history) but is no longer claimable
    rows = _manage("content_briefs", action="get_all_records")
    assert rows["count"] == 1
    assert rows["data"][0]["Generated"] == "Yes"
    again = _manage("content_briefs", action="find_row_by_key",
                    key_column="Generated", key_value="No")
    assert again["found"] is False

    # research rows are snapshots -- deleting one must not touch the ledger
    _manage("research_data", "append_row", row_values=[
        "topic gamma", "1", "1", "informational", "", "", "", "No", "k", "", ""])
    lookup = _manage("research_data", action="find_row_by_key",
                     key_column="Keyword/Topic", key_value="topic gamma")
    assert lookup["found"] is True
    _manage("research_data", action="delete_row", row_index=lookup["row_index"])
    still_there = _manage("research_data", action="get_all_records")
    assert still_there["count"] == 1


# ---------------------------------------------------------------------------
# Write side: header -> field mapping on the article row
# ---------------------------------------------------------------------------
def test_generated_posts_cell_writes_map_onto_the_article(pg_db):
    from lib.db import Article, get_session

    _site()
    _manage("generated_posts", "append_row", row_values=[
        "Title One", "## Body", "faq", "88.5", "meta summary",
        "No", "No", "bundle", "seed", "secondary kw",
    ])

    lookup = _manage("generated_posts", action="find_row_by_key",
                     key_column="Title", key_value="Title One")
    assert lookup["found"] is True and lookup["row_index"] == 2
    row_index = lookup["row_index"]

    headers = _manage("generated_posts", action="get_range", cell_range="1:1")
    header_row = headers["data"][0]

    approve_col = header_row.index("Approve/Disapprove") + 1
    res = _manage("generated_posts", action="update_cell",
                  row_index=row_index, col_index=approve_col, data="Approved")
    assert res["status"] == "success"

    published_col = header_row.index("Published") + 1
    res = _manage("generated_posts", action="update_cell",
                  row_index=row_index, col_index=published_col, data="Yes")
    assert res["status"] == "success"

    quality_col = header_row.index("Quality Score") + 1
    res = _manage("generated_posts", action="update_cell",
                  row_index=row_index, col_index=quality_col, data="91.25")
    assert res["status"] == "success"

    rows = _manage("generated_posts", action="get_all_records")
    assert rows["data"][0]["Approve/Disapprove"] == "Approved"
    assert rows["data"][0]["Published"] == "Yes"
    assert rows["data"][0]["Quality Score"] == 91.25

    s = get_session()
    try:
        art = s.query(Article).one()
        assert art.status == "published" and art.published_at is not None
        assert (art.meta or {}).get("scores", {}).get("quality") == 91.25
    finally:
        s.close()

    # header row writes are a no-op success (canonical columns are fixed)
    header_write = _manage("generated_posts", action="update_cell",
                           row_index=1, col_index=3, data="Whatever")
    assert header_write["status"] == "success"

    # update_row applies a positional row by column name
    res = _manage("generated_posts", action="update_row", row_index=row_index,
                  row_values=["Title One", "## Body 2", "faq2", "88.5",
                              "meta summary", "Approved", "Yes", "bundle",
                              "seed", "secondary kw"])
    assert res["status"] == "success"
    rows = _manage("generated_posts", action="get_all_records")
    assert rows["data"][0]["Generated Content"] == "## Body 2"
    assert rows["data"][0]["FAQs"] == "faq2"


def test_approved_unpublished_is_the_approved_filter_view(pg_db):
    """The Preparation Agent's `get_row(row_index=2)` on this worksheet is
    how a Sheets-off instance picks the next post to ship -- it must be the
    approved-and-unpublished slice of generated_posts, not an empty no-op."""
    _site()
    _manage("generated_posts", "append_row", row_values=[
        "Ship Me", "## Body", "[]", "90", "summary", "No", "No", "", "", ""])
    _manage("generated_posts", "append_row", row_values=[
        "Not Yet", "## Body", "[]", "70", "summary", "No", "No", "", "", ""])

    headers = _manage("generated_posts", action="get_range", cell_range="1:1")
    header_row = headers["data"][0]
    approve_col = header_row.index("Approve/Disapprove") + 1
    _manage("generated_posts", action="update_cell", row_index=2,
            col_index=approve_col, data="Approved")

    queued = _manage("approved_unpublished", action="get_all_records")
    assert queued["count"] == 1
    assert queued["data"][0]["Title"] == "Ship Me"
    assert queued["data"][0]["Approve/Disapprove"] == "Approved"
    row2 = _manage("approved_unpublished", action="get_row", row_index=2)
    assert row2["data"][0] == "Ship Me"
    assert _manage("approved_unpublished", action="get_row",
                   row_index=3)["data"] == []

    # publishing removes it from the filter
    published_col = header_row.index("Published") + 1
    _manage("generated_posts", action="update_cell", row_index=2,
            col_index=published_col, data="Yes")
    assert _manage("approved_unpublished", action="get_all_records")["count"] == 0
    # ...and the underlying article keeps its stamp/history
    assert _manage("generated_posts", action="get_all_records")["count"] == 2


def test_unmapped_worksheets_are_noops_when_sheets_are_off(pg_db):
    _site()
    assert _manage("claims_audit", action="get_all_records")["data"] == []
    assert _manage("published_posts", action="get_all_records")["data"] == []
    appended = _manage("published_posts", "append_row",
                       row_values=["topic", "https://x", ""])
    assert appended["status"] == "success" and appended["skipped"] is True
    found = _manage("review", action="find_row_by_key",
                    key_column="Title", key_value="anything")
    assert found["found"] is False
    # these paths stay soft (status == success + empty data) for every
    # review/repurpose/telemetry stage that reads an unmapped worksheet
    assert _manage("repurposed_content", action="get_all_records")["count"] == 0


def test_clear_sheet_refuses_in_postgres_mode(pg_db):
    _site()
    res = _manage("research_data", action="clear_sheet")
    assert res["status"] == "error" and "Postgres mode" in res["message"]


# ---------------------------------------------------------------------------
# Keyword claims (spec 3b: the queue lives in keyword_ledger)
# ---------------------------------------------------------------------------
def test_keyword_claim_is_idempotent_releases_and_skips_terminal(pg_db):
    from lib.db import KeywordLedger, get_session
    from lib.ledger import upsert_keyword
    from tools import sheet_tool

    site = _site()
    s = get_session()
    try:
        first = upsert_keyword(s, site.id, "kw one", volume=10)
        second = upsert_keyword(s, site.id, "kw two", volume=20)
        third = upsert_keyword(s, site.id, "kw three", volume=30)
        ids = (first.id, second.id, third.id)
    finally:
        s.close()

    claim = sheet_tool.claim_keyword()
    assert claim["selected_keyword"] == "kw one"
    assert claim["status_update"]

    # idempotent re-claim: a fallback re-run gets the same row back
    again = sheet_tool.claim_keyword()
    assert again["selected_keyword"] == claim["selected_keyword"]

    # a successful research run persists findings and clears the claim
    s = get_session()
    try:
        row = s.get(KeywordLedger, ids[0])
        snap = dict(row.research_snapshot or {})
        snap["summary"] = "done"
        row.research_snapshot = snap
        s.commit()
    finally:
        s.close()
    sheet_tool.clear_keyword_claim()

    second_claim = sheet_tool.claim_keyword()
    assert second_claim["selected_keyword"] == "kw two"
    assert sheet_tool.release_keyword_claim() is True

    s = get_session()
    try:
        released = s.get(KeywordLedger, ids[1])
        assert "claimed_at" not in (released.research_snapshot or {})
    finally:
        s.close()

    # after release the row is claimable again (same as the sheet's
    # Status -> "available"), so the next claim is kw two once more
    third_claim = sheet_tool.claim_keyword()
    assert third_claim["selected_keyword"] == "kw two"
    sheet_tool.clear_keyword_claim()

    # terminal rows are never handed out
    s = get_session()
    try:
        for kid in ids:
            r = s.get(KeywordLedger, kid)
            r.status = "won"
        s.commit()
    finally:
        s.close()
    exhausted = sheet_tool.claim_keyword()
    assert exhausted == {"error": "No available keywords found"}


def test_sheets_on_keeps_the_sheet_claim_path(pg_db, monkeypatch):
    """Mixed mode (site #1 today): the keyword sheet is unmapped, so claims
    keep coming from the sheet while Sheets is enabled."""
    monkeypatch.setenv("SHEETS_ENABLED", "1")
    from tools import sheet_tool

    def _no_client(*a, **k):  # pragma: no cover
        raise AssertionError("expected the gspread path, not Postgres")

    monkeypatch.setattr(sheet_tool, "get_gspread_client", _no_client)
    # sheets_enabled() is read per call, so this takes the sheet path (and
    # dies there, loudly) instead of quietly claiming from Postgres
    result = sheet_tool.claim_keyword()
    assert "error" in result
    assert result["error"].startswith("Failed to fetch keyword")
    assert "expected the gspread path" in result["error"]


# ---------------------------------------------------------------------------
# Stage-level read: published posts for the repurpose gate
# ---------------------------------------------------------------------------
def test_successful_published_posts_comes_from_articles(pg_db):
    from lib.db import Article, get_session
    from lib.ledger import upsert_keyword

    site = _site()
    s = get_session()
    try:
        kw = upsert_keyword(s, site.id, "published kw")
        art = Article(site_id=site.id, keyword_id=kw.id, title="Published One",
                      status="published", content_md="body",
                      meta={"wp_url": "https://example.test/blog/published-one",
                            "scores": {"quality": 90}})
        draft = Article(site_id=site.id, title="Draft One", status="generated",
                        content_md="x", meta={})
        s.add_all([art, draft])
        s.commit()
    finally:
        s.close()

    import scripts.run_stage as rs

    rows = rs._get_successful_published_posts()
    assert len(rows) == 1
    assert rows[0]["Keyword/Topic"] == "published kw"
    assert rows[0]["Title"] == "Published One"
    assert rows[0]["Post URL"] == "https://example.test/blog/published-one"
    assert rows[0]["Error"] == ""

    # without a keyword link the title stands in for the topic
    s = get_session()
    try:
        draft = s.query(Article).filter(Article.title == "Draft One").one()
        draft.status = "published"
        draft.keyword_id = None
        draft.meta = {"post_url": "https://example.test/blog/draft-one"}
        s.commit()
    finally:
        s.close()
    rows = rs._get_successful_published_posts()
    assert {r["Keyword/Topic"] for r in rows} == {"published kw", "Draft One"}
    assert all(r["Post URL"] for r in rows)


def test_ensure_worksheet_exists_noops_with_sheets_off(pg_db):
    from tools import sheet_tool

    assert sheet_tool.ensure_worksheet_exists(
        "claims_audit", ["Title", "Keyword/Topic"]) is True
    assert sheet_tool.ensure_worksheet_exists(
        "research_data", ["Keyword/Topic"]) is True
