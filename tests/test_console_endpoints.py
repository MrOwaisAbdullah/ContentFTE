"""Operator-console backing endpoints (spec-site2-postgres-frontend §5):
queue view, read-only brief peek, PATCH content, run/{stage} trigger."""
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
