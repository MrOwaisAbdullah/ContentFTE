"""Operator-console backing endpoints (spec-site2-postgres-frontend §5):
queue view, read-only brief peek, PATCH content, run/{stage} trigger,
research/briefs/logs worksheet views, usage-log audit mirror."""
import os

import pytest


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch):
    workdir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           ".test-tmp-console")
    os.makedirs(workdir, exist_ok=True)
    db_file = os.path.join(workdir, "console.db")
    try:
        os.remove(db_file)
    except OSError:
        pass
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.delenv("SDK_MASTER_KEY", raising=False)
    monkeypatch.delenv("WP_BASE_URL", raising=False)
    import lib.db as db

    if db._engine is not None:
        db._engine.dispose()
    db._engine = None
    db._SessionLocal = None
    try:
        os.remove(db_file)
    except OSError:
        pass
    from sdk import service

    service.init()
    yield
    if db._engine is not None:
        db._engine.dispose()
    try:
        os.remove(db_file)
    except OSError:
        pass


def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from sdk.server import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _seed_ledger(site_slug: str, specs):
    """Create the site and ledger rows; returns [ledger_id, ...]."""
    from sqlalchemy import select

    from lib.db import Site, get_session
    from lib.ledger import set_status, upsert_keyword
    from sdk import service

    service.upsert_site(site_slug, name=site_slug.title())
    ids = []
    s = get_session()
    try:
        site = s.execute(select(Site).where(Site.slug == site_slug)).scalars().first()
        for keyword, status in specs:
            row = upsert_keyword(s, site.id, keyword)
            set_status(s, row.id, status)
            ids.append(row.id)
    finally:
        s.close()
    return ids


def test_queue_route_returns_rows_and_counts():
    ids = _seed_ledger("acme", [
        ("how to tie a tie", "approved"),
        ("best crm software", "researched"),
        ("email marketing guide", "queued"),
    ])
    client = _client()

    res = client.get("/sdk/v1/sites/acme/queue")
    assert res.status_code == 200
    body = res.json()
    assert body["site"] == "acme"
    assert body["counts"] == {"approved": 1, "researched": 1, "queued": 1}
    assert body["count"] == 3
    # newest-first
    assert [r["keyword"] for r in body["queue"]] == [
        "email marketing guide", "best crm software", "how to tie a tie"]
    assert body["queue"][2]["id"] == ids[0]

    filtered = client.get("/sdk/v1/sites/acme/queue?status=approved").json()
    assert filtered["count"] == 1
    assert filtered["queue"][0]["keyword"] == "how to tie a tie"

    missing = client.get("/sdk/v1/sites/nope/queue")
    assert missing.status_code == 404


def test_brief_route_is_read_only_peek():
    _seed_ledger("acme", [("how to tie a tie", "approved")])
    client = _client()

    brief = client.get("/sdk/v1/sites/acme/brief")
    assert brief.status_code == 200
    assert brief.json()["keyword"] == "how to tie a tie"

    # the GET must not claim/consume the row — still there, still approved
    again = client.get("/sdk/v1/sites/acme/brief")
    assert again.json()["keyword"] == "how to tie a tie"
    queue = client.get("/sdk/v1/sites/acme/queue").json()
    assert queue["counts"] == {"approved": 1}

    client.post("/sdk/v1/sites", json={"slug": "empty-site"})
    assert client.get("/sdk/v1/sites/empty-site/brief").json()["status"] == "empty"


def test_patch_content_updates_and_reopens_approved():
    from sdk import service

    art = service.submit_article("acme", keyword="how to tie a tie")
    service.approve_article(art["id"], approved=True, note="gate passed")
    client = _client()

    res = client.patch(f"/sdk/v1/articles/{art['id']}/content",
                       json={"content_md": "# Edited\n\nNew body.",
                             "note": "operator fix"})
    assert res.status_code == 200
    body = res.json()
    assert body["reopened"] is True
    assert body["status"] == "generated"
    assert body["edits"] == 1

    got = service.get_article(art["id"], include_content=True)
    assert got["markdown"].startswith("# Edited")
    assert got["meta"]["edit_log"][-1]["note"] == "operator fix"


def test_patch_content_keeps_published_status():
    from sdk import service

    art = service.submit_article("acme", keyword="published kw")
    service.approve_article(art["id"], approved=True)
    service.publish_article(art["id"], mode="draft")
    client = _client()

    res = client.patch(f"/sdk/v1/articles/{art['id']}/content",
                       json={"content_md": "# Live edit"})
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "published"
    assert body["reopened"] is False

    empty = client.patch(f"/sdk/v1/articles/{art['id']}/content",
                         json={"content_md": "   "})
    assert empty.status_code == 404


def test_run_stage_route_accept_unknown_and_overlap(monkeypatch):
    import sdk.server as server
    from scripts import run_stage as run_stage_mod

    calls = []

    async def _stub():
        calls.append("ran")

    monkeypatch.setattr(run_stage_mod, "STAGE_HANDLERS", {"stub_stage": _stub})
    client = _client()

    unknown = client.post("/sdk/v1/run/not_a_stage")
    assert unknown.status_code == 404
    assert "valid" in unknown.json()["detail"]

    server._running_stages.add("stub_stage")
    overlap = client.post("/sdk/v1/run/stub_stage")
    assert overlap.status_code == 409
    server._running_stages.discard("stub_stage")

    accepted = client.post("/sdk/v1/run/stub_stage")
    assert accepted.status_code == 202
    assert accepted.json() == {"status": "accepted", "stage": "stub_stage"}
    # TestClient drains background tasks before returning the response
    assert calls == ["ran"]
    assert "stub_stage" not in server._running_stages


def _seed_research_and_brief(site_slug: str):
    """Mirror a research row + its brief into the ledger snapshot."""
    from lib.store import mirror_brief, mirror_keyword

    s = __import__("lib.db", fromlist=["get_session"]).get_session()
    try:
        mirror_keyword(s, keyword="how to tie a tie", volume=900, difficulty=21.0,
                       intent="informational", summary="A tie-tying explainer.",
                       subject="How to tie a tie", primary_keyword="how to tie a tie",
                       secondary_keywords="windsor knot, four in hand", site_slug=site_slug)
        mirror_brief(s, keyword="how to tie a tie", brief_content="# Brief\n\nSteps…",
                     faqs='[{"question":"Q","answer":"A"}]',
                     sources="https://example.com/src", summary="Covers 4 knots.",
                     secondary_keywords="windsor knot", site_slug=site_slug)
        mirror_keyword(s, keyword="best crm software", volume=12000, difficulty=55.0,
                       intent="commercial", summary="CRM comparison.",
                       subject="Best CRM software", primary_keyword="best crm software",
                       site_slug=site_slug)
    finally:
        s.close()


def test_research_route_returns_snapshot_fields():
    _seed_research_and_brief("acme")
    client = _client()

    res = client.get("/sdk/v1/sites/acme/research")
    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 2
    tie = next(r for r in body["research"] if r["keyword"] == "how to tie a tie")
    assert tie["subject"] == "How to tie a tie"
    assert tie["volume"] == 900
    assert tie["difficulty"] == 21.0
    # mirror_brief refreshes summary/secondary_keywords in the same snapshot,
    # so the brief's values are what the research screen shows afterwards.
    assert tie["summary"] == "Covers 4 knots."
    assert tie["secondary_keywords"] == "windsor knot"
    assert tie["generated"] is True          # brief present in snapshot
    crm = next(r for r in body["research"] if r["keyword"] == "best crm software")
    assert crm["generated"] is False

    assert client.get("/sdk/v1/sites/nope/research").status_code == 404


def test_briefs_route_only_rows_with_a_brief():
    _seed_research_and_brief("acme")
    client = _client()

    res = client.get("/sdk/v1/sites/acme/briefs")
    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 1
    b = body["briefs"][0]
    assert b["keyword"] == "how to tie a tie"
    assert b["brief"].startswith("# Brief")
    assert "example.com/src" in b["sources"]
    assert b["summary"] == "Covers 4 knots."

    assert client.get("/sdk/v1/sites/nope/briefs").status_code == 404


def test_logs_route_audit_and_costs_with_kind_filter():
    from lib.db import AuditLog, get_session
    from sdk import service

    art = service.submit_article("acme", keyword="how to tie a tie")
    s = get_session()
    try:
        s.add(AuditLog(article_id=art["id"], action="article.submit",
                       payload={"keyword": "how to tie a tie"}))
        s.commit()
    finally:
        s.close()
    from lib.store import log_usage_event
    assert log_usage_event("model", {"model": "m1", "stage": "content"}) is True
    assert log_usage_event("image", {"model": "img1", "stage": "generate"}) is True
    # cost row for the cost-ledger section
    from lib.db import CostLedger
    s = get_session()
    try:
        s.add(CostLedger(article_id=art["id"], kind="llm", amount_usd=0.0123,
                         detail={"model": "m1"}))
        s.commit()
    finally:
        s.close()

    client = _client()
    res = client.get("/sdk/v1/logs")
    assert res.status_code == 200
    body = res.json()
    actions = [a["action"] for a in body["audit"]]
    assert "article.submit" in actions
    assert "usage.model" in actions
    assert "usage.image" in actions
    assert body["costs"][0]["kind"] == "llm"
    assert body["costs"][0]["amount_usd"] == pytest.approx(0.0123)

    usage = client.get("/sdk/v1/logs?kind=usage").json()
    usage_actions = {a["action"] for a in usage["audit"]}
    assert usage_actions == {"usage.model", "usage.image"}
    assert usage["costs"] == []

    cost = client.get("/sdk/v1/logs?kind=cost").json()
    assert cost["audit"] == []
    assert len(cost["costs"]) == 1


def test_usage_log_functions_mirror_to_audit_when_sheets_fail(monkeypatch):
    import tools.sheet_tool as st
    from lib.db import AuditLog, get_session

    def _no_sheets():
        raise RuntimeError("no sheets in test")

    monkeypatch.setattr(st, "get_spreadsheet", _no_sheets)

    assert st.log_model_usage("model-x", "agent-y", "content", "ok", 1.5) is True
    assert st.log_image_usage("img-model", "generate", "puppy", "ok", 2.0,
                              cost_usd=0.001, slot="featured", prompt="a puppy") is True

    s = get_session()
    try:
        rows = s.execute(select_audit()).scalars().all()
    finally:
        s.close()
    by_action = {r.action: r.payload for r in rows
                 if r.action in ("usage.model", "usage.image")}
    assert by_action["usage.model"]["model"] == "model-x"
    assert by_action["usage.model"]["agent"] == "agent-y"
    assert by_action["usage.model"]["latency"] == "1.5"
    assert by_action["usage.image"]["subject"] == "puppy"
    assert by_action["usage.image"]["cost_usd"] == "0.0010"


def select_audit():
    from sqlalchemy import select

    from lib.db import AuditLog
    return select(AuditLog)


def test_list_articles_carries_quality_and_summary():
    from lib.db import get_session
    from lib.store import mirror_article
    from sdk import service

    s = get_session()
    try:
        mirror_article(s, title="Tie Guide", content="# Body", quality_score=92.5,
                       summary="A strong tie guide.", approved=True,
                       site_slug="acme")
    finally:
        s.close()

    client = _client()
    body = client.get("/sdk/v1/articles?site_slug=acme").json()
    row = next(a for a in body["articles"] if a["title"] == "Tie Guide")
    assert row["quality"] == 92.5
    assert row["summary"] == "A strong tie guide."
    assert row["status"] == "approved"


def test_upsert_site_updates_existing_row():
    from sdk import service

    first = service.upsert_site("up-site", name="Old Name", site_type="wordpress",
                                base_url="http://old.test")
    assert first["created"] is True
    assert first["updated"] is False

    second = service.upsert_site("up-site", name="New Name", site_type="custom",
                                 base_url="http://new.test")
    assert second["created"] is False
    assert second["updated"] is True
    row = {s["slug"]: s for s in service.list_sites()["sites"]}["up-site"]
    assert row["name"] == "New Name"
    assert row["site_type"] == "custom"
    assert row["base_url"] == "http://new.test"

    # empty strings leave every field untouched (no clobber from defaults)
    third = service.upsert_site("up-site")
    assert third["created"] is False
    assert third["updated"] is False
    row = {s["slug"]: s for s in service.list_sites()["sites"]}["up-site"]
    assert row["name"] == "New Name"
    assert row["base_url"] == "http://new.test"

    # create still defaults site_type when none is given
    service.upsert_site("fresh-site")
    fresh = {s["slug"]: s for s in service.list_sites()["sites"]}["fresh-site"]
    assert fresh["site_type"] == "custom"


def test_sites_route_update_keeps_site_type_when_omitted():
    from sdk import service

    client = _client()
    created = client.post("/sdk/v1/sites", json={"slug": "api-site", "name": "One",
                                                 "site_type": "wordpress",
                                                 "base_url": "http://wp.test"})
    assert created.status_code == 200
    assert created.json()["created"] is True

    # name-only update: site_type omitted from the body must not downgrade
    # the row back to the model default
    updated = client.post("/sdk/v1/sites", json={"slug": "api-site", "name": "Two"})
    assert updated.status_code == 200
    assert updated.json()["created"] is False
    assert updated.json()["updated"] is True
    row = {s["slug"]: s for s in service.list_sites()["sites"]}["api-site"]
    assert row["name"] == "Two"
    assert row["site_type"] == "wordpress"
    assert row["base_url"] == "http://wp.test"
