"""Live-Postgres smoke for the DATABASE_URL switch (env-gated).

Skipped unless TEST_PG_URL points at a **throwaway Postgres database** (a
Neon branch or a local server). It seeds a tiny sqlite store, copies it into
Postgres through scripts/copy_sqlite_to_postgres.py (ids preserved,
sequences advanced), then points the engine (lib.db + sdk.service) at
Postgres and runs a real write/read cycle: site listing, article submit +
approve, stage-run recording, log listing.

It writes into the target and cleans up the rows it created; never aim it at
anything you care about.

Run:
    $env:TEST_PG_URL='postgresql+psycopg://user:pass@host/db?sslmode=require'
    uv run python -m pytest tests/test_postgres_smoke.py -q
"""
from __future__ import annotations

import os
import uuid

import pytest

PG_URL = os.environ.get("TEST_PG_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not PG_URL, reason="TEST_PG_URL not set — point it at a throwaway Postgres DB")


def _seed_sqlite(url: str, slug: str) -> dict:
    """One site + one linked article/cost/audit row in a fresh sqlite file."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from lib.db import Article, AuditLog, Base, CostLedger, KeywordLedger, Site

    eng = create_engine(url)
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        site = Site(slug=slug, name="PG Smoke", base_url="https://pg.test")
        s.add(site)
        s.flush()
        kw = KeywordLedger(site_id=site.id, keyword=f"{slug} keyword",
                           status="approved")
        s.add(kw)
        s.flush()
        art = Article(site_id=site.id, keyword_id=kw.id, title="Copied to PG",
                      slug=f"{slug}-article", status="generated",
                      content_md="# Copied\n\nHello from sqlite.",
                      meta={"brief": {"description": "copied"}})
        s.add(art)
        s.flush()
        s.add(CostLedger(article_id=art.id, kind="llm", amount_usd=0.011,
                         detail={"model": "seed"}))
        s.add(AuditLog(article_id=art.id, site_id=site.id,
                       action="article.generate", payload={"seed": True}))
        s.commit()
        ids = {"site": site.id, "article": art.id}
    eng.dispose()
    return ids


@pytest.fixture()
def pg_env(tmp_path, monkeypatch):
    """sqlite seed -> copy into PG -> engine aimed at PG for the test."""
    from sqlalchemy import create_engine, text

    from scripts.copy_sqlite_to_postgres import copy_store

    slug = f"pg-smoke-{uuid.uuid4().hex[:8]}"
    src_url = f"sqlite:///{(tmp_path / 'seed.db').as_posix()}"
    ids = _seed_sqlite(src_url, slug)

    report = copy_store(src_url, PG_URL, log=lambda *_: None)
    assert report["sequences_reset"] is True, \
        "PG target must take the sequence-reset branch"

    import lib.db as db

    if db._engine is not None:
        db._engine.dispose()
    monkeypatch.setenv("DATABASE_URL", PG_URL)  # service() resolves at call time
    db._engine = None
    db._SessionLocal = None

    from sdk import service

    service.init()
    yield {"slug": slug, **ids}

    # Teardown: drop this run's rows (FK order), then release the engine.
    if db._engine is not None:
        db._engine.dispose()
    db._engine = None
    db._SessionLocal = None
    eng = create_engine(PG_URL)
    try:
        sid = f"(SELECT id FROM sites WHERE slug = '{slug}')"
        with eng.begin() as conn:
            conn.execute(text(
                f"DELETE FROM audit_log WHERE site_id = {sid} OR article_id IN "
                f"(SELECT id FROM articles WHERE site_id = {sid})"))
            conn.execute(text(
                f"DELETE FROM audit_log WHERE action = 'stage.run' "
                f"AND payload->>'detail' = 'pg smoke'"))
            conn.execute(text(
                f"DELETE FROM cost_ledger WHERE article_id IN "
                f"(SELECT id FROM articles WHERE site_id = {sid})"))
            conn.execute(text(f"DELETE FROM articles WHERE site_id = {sid}"))
            conn.execute(text(f"DELETE FROM keyword_ledger WHERE site_id = {sid}"))
            conn.execute(text(f"DELETE FROM sites WHERE slug = '{slug}'"))
    finally:
        eng.dispose()


def test_engine_service_cycle_on_postgres(pg_env):
    from sdk import service

    slug = pg_env["slug"]

    # The copied rows are readable through the service on PG.
    sites = service.list_sites()["sites"]
    assert any(s["slug"] == slug for s in sites)
    copied = service.get_article(pg_env["article"], include_content=True)
    assert copied["title"] == "Copied to PG"

    # A brand-new insert must not collide with the copied ids — this is the
    # sequence-reset assertion, observed from the write path.
    res = service.submit_article(slug, keyword="pg smoke keyword")
    assert "error" not in res, res
    assert res["id"] != pg_env["article"]
    assert service.get_article(res["id"])["status"] == "briefed"

    service.approve_article(res["id"], approved=True, note="pg smoke")
    assert service.get_article(res["id"])["status"] == "approved"

    service.record_stage_run("research", ok=True, detail="pg smoke",
                             duration_ms=42)
    stages = service.list_stages(running=["brief"], limit=50)
    assert stages["running"] == ["brief"]
    assert stages["last"]["research"]["ok"] is True

    logs = service.list_logs(kind="stage", limit=50, offset=0)
    assert logs.get("count", 0) >= 1
