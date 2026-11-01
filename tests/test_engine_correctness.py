"""Plan ENG-03 / 04 / 06 / 07 / 10 / 17: single-flight, non-blocking MCP, no data loss on re-submit,
no status regression, sane page sizes."""
from __future__ import annotations

import asyncio
import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'correct.db'}")
    import lib.db as db
    if db._engine is not None:
        db._engine.dispose()
    db._engine = None
    db._SessionLocal = None
    from sdk import service
    service.init()
    service.upsert_site("s", "S", "custom", "https://s.test", {"require_approval": False})
    yield service
    if db._engine is not None:
        db._engine.dispose()
    db._engine = None
    db._SessionLocal = None


# ------------------------------------------------------------------ ENG-07: re-submit must not wipe research
def test_resubmitting_a_keyword_keeps_its_metrics_and_queue_position(svc):
    from lib.db import KeywordLedger, Site, get_session
    from lib.ledger import priority_score, upsert_keyword
    s = get_session()
    try:
        site = s.query(Site).filter_by(slug="s").one()
        row = upsert_keyword(s, site.id, "ai agents", intent="commercial", volume=900, difficulty=30.0)
        original = (row.intent, row.volume, row.difficulty, row.priority_score)
        assert original[3] == priority_score(900, "commercial", 30.0)
        again = upsert_keyword(s, site.id, "ai agents")                 # what submit_article does
        assert (again.intent, again.volume, again.difficulty, again.priority_score) == original
        assert s.query(KeywordLedger).filter_by(keyword="ai agents").count() == 1
    finally:
        s.close()


def test_updating_one_metric_changes_only_that_metric_and_re_ranks(svc):
    from lib.db import Site, get_session
    from lib.ledger import priority_score, upsert_keyword
    s = get_session()
    try:
        site = s.query(Site).filter_by(slug="s").one()
        upsert_keyword(s, site.id, "kw", intent="commercial", volume=100, difficulty=10.0)
        row = upsert_keyword(s, site.id, "kw", volume=500)
        assert (row.intent, row.volume, row.difficulty) == ("commercial", 500, 10.0)
        assert row.priority_score == priority_score(500, "commercial", 10.0)
    finally:
        s.close()


def test_brand_new_keywords_still_get_the_old_defaults(svc):
    from lib.db import Site, get_session
    from lib.ledger import upsert_keyword
    s = get_session()
    try:
        row = upsert_keyword(s, s.query(Site).filter_by(slug="s").one().id, "fresh")
        assert (row.intent, row.volume, row.difficulty, row.priority_score) == ("informational", 0, 0.0, 0.0)
        assert row.status == "researched"
    finally:
        s.close()


def test_submit_article_twice_does_not_erase_the_ledger_row(svc):
    from lib.db import KeywordLedger, get_session
    svc.submit_article("s", keyword="kept kw")
    s = get_session()
    try:
        row = s.query(KeywordLedger).filter_by(keyword="kept kw").one()
        row.volume, row.intent = 1234, "commercial"
        s.commit()
    finally:
        s.close()
    svc.submit_article("s", keyword="kept kw")
    s = get_session()
    try:
        row = s.query(KeywordLedger).filter_by(keyword="kept kw").one()
        assert (row.volume, row.intent) == (1234, "commercial")
    finally:
        s.close()


# ------------------------------------------------------------------ ENG-10: approving a live article
def test_approving_a_published_article_does_not_regress_it(svc):
    from lib.db import Article, get_session
    aid = svc.submit_article("s", keyword="live")["id"]
    s = get_session()
    try:
        a = s.get(Article, aid)
        a.status, a.content_md = "published", "body"
        s.commit()
    finally:
        s.close()
    out = svc.approve_article(aid, True)
    assert out["status"] == "published" and "unchanged" in out["note"]
    assert svc.get_article(aid)["status"] == "published"
    # reopening a published article is still an explicit operator decision
    assert svc.approve_article(aid, False)["status"] == "needs_review"


# ------------------------------------------------------------------ ENG-17: page sizes
@pytest.mark.parametrize("bad", [-5, 0, "abc", None, 10**9])
def test_list_functions_survive_hostile_limits(svc, bad):
    svc.submit_article("s", keyword="one")
    for out in (svc.list_queue("s", limit=bad), svc.list_research("s", limit=bad),
                svc.list_briefs("s", limit=bad), svc.list_logs(limit=bad),
                svc.list_review_feedback("s", limit=bad)):
        assert "error" not in out


def test_a_negative_limit_is_a_page_of_one_not_unlimited(svc):
    for i in range(5):
        svc.submit_article("s", keyword=f"kw{i}")
    assert len(svc.list_logs(limit=-1)["audit"]) == 1
    assert svc._clamp_limit(10**9) == 500 and svc._clamp_limit("x") == 100 and svc._clamp_limit(None, 200) == 200


# ------------------------------------------------------------------ ENG-03: single-flight publish
def test_a_second_concurrent_publish_is_refused_instead_of_racing(svc, monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def slow_locked(article_id, **kw):
        entered.set()
        assert release.wait(5), "test deadlock"
        return {"id": article_id, "status": "published"}

    monkeypatch.setattr(svc, "_publish_article_locked", slow_locked)
    first = {}
    t = threading.Thread(target=lambda: first.update(svc.publish_article(7)))
    t.start()
    assert entered.wait(5)
    second = svc.publish_article(7)                                  # while the first is mid-flight
    assert second["code"] == "publish_in_progress" and "already being published" in second["error"]
    assert svc._claim("publish", 8) is True                          # a different article is not blocked
    svc._release("publish", 8)
    release.set()
    t.join(5)
    assert first["status"] == "published"
    assert svc.publish_article(7)["status"] == "published"           # slot released afterwards


def test_the_slot_is_released_even_when_publish_raises(svc, monkeypatch):
    def boom(article_id, **kw):
        raise RuntimeError("wordpress exploded")
    monkeypatch.setattr(svc, "_publish_article_locked", boom)
    with pytest.raises(RuntimeError):
        svc.publish_article(3)
    monkeypatch.setattr(svc, "_publish_article_locked", lambda article_id, **kw: {"status": "published"})
    assert svc.publish_article(3)["status"] == "published"


def test_rest_returns_409_for_a_concurrent_publish(svc, monkeypatch):
    from sdk.server import router
    monkeypatch.setenv("SDK_ALLOW_UNAUTHENTICATED", "1")
    monkeypatch.delenv("SDK_MASTER_KEY", raising=False)
    app = FastAPI()
    app.include_router(router)
    c = TestClient(app, raise_server_exceptions=False)
    assert svc._claim("publish", 42)                                  # simulate one already running
    try:
        r = c.post("/sdk/v1/articles/42/publish", json={})
    finally:
        svc._release("publish", 42)
    assert r.status_code == 409 and "already being published" in r.json()["detail"]


# ------------------------------------------------------------------ ENG-04: single-flight generation
def test_a_second_concurrent_generation_does_not_pay_for_another_llm_run(svc):
    aid = svc.submit_article("s", keyword="gen kw")["id"]
    calls = {"n": 0}
    gate = asyncio.Event()

    async def slow_generate(brief):
        calls["n"] += 1
        await gate.wait()
        return {"Title": "T", "Generated Content": "x " * 80, "Summary": "s", "Quality Score": "80"}

    async def scenario():
        first = asyncio.create_task(svc.generate_content(aid, generate_fn=slow_generate))
        await asyncio.sleep(0.05)                                   # let it enter the generator
        second = await svc.generate_content(aid, generate_fn=slow_generate)
        gate.set()
        await first
        return second

    second = asyncio.run(scenario())
    assert second["code"] == "generation_in_progress"
    assert calls["n"] == 1                                          # the LLM ran once


# ------------------------------------------------------------------ ENG-06: MCP must not block the loop
def test_blocking_service_calls_run_off_the_event_loop():
    import sdk.service as real
    from mcp_server.server import _ThreadedService

    proxy = _ThreadedService()
    real._test_blocker = lambda: time.sleep(0.4) or "done"
    try:
        async def scenario():
            ticks = 0

            async def ticker():
                nonlocal ticks
                while True:
                    await asyncio.sleep(0.02)
                    ticks += 1

            t = asyncio.create_task(ticker())
            result = await proxy._test_blocker()
            t.cancel()
            return result, ticks

        result, ticks = asyncio.run(scenario())
    finally:
        del real._test_blocker
    assert result == "done"
    assert ticks >= 8, f"the event loop was blocked during the service call (only {ticks} ticks)"


def test_the_proxy_passes_coroutine_functions_through_and_sees_monkeypatches(monkeypatch):
    import sdk.service as real
    from mcp_server.server import _ThreadedService

    proxy = _ThreadedService()
    assert proxy.generate_content is real.generate_content           # async fn: untouched
    monkeypatch.setattr(real, "list_sites", lambda: {"patched": True})
    assert asyncio.run(proxy.list_sites()) == {"patched": True}      # resolved at call time
    with pytest.raises(AttributeError):
        proxy.definitely_not_a_function
