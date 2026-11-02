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


# ------------------------------------------------------------------ ENG-20: no search-engine ping for a draft
def _wp_article(svc):
    from lib.db import Article, get_session
    svc.upsert_site("wp", "WP", "wordpress", "https://wp.test", {"require_approval": False})
    aid = svc.submit_article("wp", keyword="a draft")["id"]
    s = get_session()
    try:
        a = s.get(Article, aid)
        a.status, a.content_md, a.title = "approved", "# T\n\nbody", "T"
        s.commit()
    finally:
        s.close()
    return aid


@pytest.mark.parametrize("wp_state,mode,pinged", [
    ({"ok": True, "post_id": 5, "url": "https://wp.test/a", "status": "draft"}, "draft", False),
    ({"ok": True, "post_id": 5, "url": "https://wp.test/a", "status": "publish"}, "auto", True),
    ({"ok": False, "error": "boom"}, "auto", False),
    ({"ok": True, "deduplicated": True, "post_id": 5, "url": "https://wp.test/a"}, "draft", False),
])
def test_indexing_is_only_pinged_for_a_page_that_is_actually_live(svc, monkeypatch, wp_state, mode, pinged):
    aid = _wp_article(svc)
    pings = []
    monkeypatch.setattr(svc, "_wp_push", lambda art, meta, m: wp_state)
    monkeypatch.setattr(svc, "_stage_images_for", lambda *a, **k: {})
    import lib.indexing as indexing
    monkeypatch.setattr(indexing, "submit_published", lambda url, **k: pings.append(url) or {"ok": True})
    out = svc.publish_article(aid, mode=mode)
    assert bool(pings) is pinged, out
    if not pinged:
        assert "skipped" in out["indexing"]


def test_a_custom_site_publish_still_pings(svc, monkeypatch):
    pings = []
    import lib.indexing as indexing
    monkeypatch.setattr(indexing, "submit_published", lambda url, **k: pings.append(url) or {"ok": True})
    from lib.db import Article, get_session
    aid = svc.submit_article("s", keyword="custom one")["id"]
    s = get_session()
    try:
        a = s.get(Article, aid)
        a.status, a.content_md = "approved", "# T\n\nbody"
        s.commit()
    finally:
        s.close()
    svc.publish_article(aid)
    assert len(pings) == 1


# ------------------------------------------------------------------ ENG-14: idempotency cache
def test_idempotency_entries_expire_and_the_cache_is_bounded():
    from sdk.idempotency import IdempotencyCache
    now = [0.0]
    c = IdempotencyCache(ttl=100, max_entries=3, clock=lambda: now[0])
    c.set("a", {"v": 1})
    now[0] = 99
    assert c.get("a") == {"v": 1}
    now[0] = 101
    assert c.get("a") is None                       # the documented 24h window actually ends
    for k in "bcdef":
        c.set(k, {"k": k})
    assert len(c) == 3 and c.get("b") is None and c.get("f") == {"k": "f"}   # oldest evicted, newest kept


def test_a_replay_is_a_copy_so_one_handler_cannot_corrupt_later_replays():
    from sdk.idempotency import IdempotencyCache
    c = IdempotencyCache()
    c.set("k", {"id": 1})
    got = c.get("k")
    got["instant_triggered"] = True
    assert c.get("k") == {"id": 1}


# ------------------------------------------------------------------ ENG-13: no phantom tenants from a typo
def test_submit_refuses_an_unknown_site_when_the_caller_forbids_creation(svc):
    out = svc.submit_article("blgo", keyword="x", create_site=False)           # what REST/MCP pass by default
    assert "error" in out and "not found" in out["error"]
    from lib.db import Site, get_session
    s = get_session()
    try:
        assert s.query(Site).filter_by(slug="blgo").count() == 0
    finally:
        s.close()
    assert "id" in svc.submit_article("s", keyword="ok", create_site=False)    # a real site still works


def test_site_slugs_are_validated_on_creation(svc):
    for bad in ("Has Space", "a/b", "../x", "UPPER", "-lead", "x" * 64, ""):
        assert not svc.valid_site_slug(bad), bad
        assert "error" in svc.submit_article(bad, keyword="x") or bad == ""
        assert "error" in svc.upsert_site(bad, "n", "custom", "https://x.test", {}) or bad == ""
    assert svc.valid_site_slug("good-site-2")


def test_the_entry_points_opt_in_only_for_the_default_site_or_by_env(svc, monkeypatch):
    from lib.store import DEFAULT_SITE_SLUG
    monkeypatch.delenv("SDK_AUTO_CREATE_SITES", raising=False)
    assert svc._may_autocreate_site(DEFAULT_SITE_SLUG) is True
    assert svc._may_autocreate_site("anything-else") is False
    monkeypatch.setenv("SDK_AUTO_CREATE_SITES", "1")
    assert svc._may_autocreate_site("anything-else") is True


# ------------------------------------------------------------------ ADP-04 / SEC-13: custom-site delivery
def _approved_custom(svc, settings):
    from lib.db import Article, get_session
    svc.upsert_site("hooked", "H", "custom", "https://hooked.test", settings)
    aid = svc.submit_article("hooked", keyword="hook me")["id"]
    s = get_session()
    try:
        a = s.get(Article, aid)
        a.status, a.content_md, a.title = "approved", "# T\n\nbody text here", "T"
        s.commit()
    finally:
        s.close()
    return aid


def test_publish_pushes_a_signed_delivery_to_the_sites_own_webhook(svc, monkeypatch):
    sent = []
    from lib import custom_site
    monkeypatch.setattr(custom_site, "deliver", lambda payload, webhook_url="", secret="", **k:
                        sent.append((webhook_url, secret, payload)) or {"status": "ok", "status_code": 200,
                                                                         "attempts": 1, "delivery_id": "d1", "signed": True})
    aid = _approved_custom(svc, {"require_approval": False,
                                 "delivery": {"webhook_url": "https://hooked.test/api/cfte", "secret": "shh"}})
    out = svc.publish_article(aid)
    assert out["delivery"]["status"] == "ok"
    url, secret, payload = sent[0]
    assert url == "https://hooked.test/api/cfte" and secret == "shh"
    assert payload["article_id"] == aid and payload["event"] == "article.published" and "html" in payload
    # the audit row records the outcome but never the secret
    from lib.db import AuditLog, get_session
    s = get_session()
    try:
        row = s.query(AuditLog).filter_by(article_id=aid, action="article.delivery").one()
        assert "shh" not in str(row.payload) and row.payload["status"] == "ok"
    finally:
        s.close()


def test_no_webhook_configured_means_no_delivery_and_no_noise(svc, monkeypatch):
    monkeypatch.delenv("SITE_PUBLISH_WEBHOOK", raising=False)
    aid = _approved_custom(svc, {"require_approval": False})
    assert "delivery" not in svc.publish_article(aid)


def test_the_process_wide_webhook_is_not_used_in_shared_mode(svc, monkeypatch):
    monkeypatch.setenv("SITE_PUBLISH_WEBHOOK", "https://one-site.test/hook")
    monkeypatch.setenv("TENANCY_MODE", "shared")
    assert svc._delivery_target(type("S", (), {"settings": {}})()) == ("", "")
    monkeypatch.setenv("TENANCY_MODE", "isolated")
    assert svc._delivery_target(type("S", (), {"settings": {}})())[0] == "https://one-site.test/hook"


def test_delivery_secrets_never_leave_through_the_site_api(svc):
    from lib.secrets_redact import redact_settings
    clean, flags = redact_settings({"delivery": {"webhook_url": "https://x.test/h?token=abc", "secret": "shh"}})
    assert "shh" not in str(clean) and "token=abc" not in str(clean)
    assert flags["delivery_secret"] is True and flags["delivery_webhook_url"] is True


# ------------------------------------------------------------------ ENG-17: typed meta patch, bad settings
def test_a_garbage_numeric_setting_degrades_to_the_default_instead_of_crashing(svc):
    f = svc._int_setting
    assert f("abc", default=1, lo=1, hi=100) == 1
    assert f(None, default=3, lo=1, hi=100) == 3
    assert f({"x": 1}, default=2, lo=1, hi=100) == 2
    assert f("7", default=1, lo=1, hi=100) == 7 and f(7.9, default=1, lo=1, hi=100) == 7
    assert f(-5, default=1, lo=1, hi=100) == 1 and f(10**9, default=1, lo=1, hi=100) == 100
    assert f(float("inf"), default=4, lo=1, hi=100) == 4
    from lib.db import Site, get_session
    s = get_session()
    try:
        site = s.query(Site).filter_by(slug="s").one()
        site.settings = {**(site.settings or {}), "max_posts_per_cadence": "lots", "posting_frequency": "daily"}
        s.commit()
        assert svc.get_site_cadence_status(s, site)["max_posts_per_cadence"] == 1     # was a ValueError
    finally:
        s.close()


def test_meta_patch_rejects_wrong_types_and_oversized_values(svc):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sdk.server import router
    monkey_app = FastAPI()
    monkey_app.include_router(router)
    import os
    os.environ["SDK_ALLOW_UNAUTHENTICATED"] = "1"
    try:
        c = TestClient(monkey_app)
        aid = svc.submit_article("s", keyword="meta kw")["id"]
        assert c.patch(f"/sdk/v1/articles/{aid}/meta", json={"title": ["a", "list"]}).status_code == 422
        assert c.patch(f"/sdk/v1/articles/{aid}/meta", json={"title": "x" * 301}).status_code == 422
        ok = c.patch(f"/sdk/v1/articles/{aid}/meta", json={"title": "A real title", "ignored": "x"})
        assert ok.status_code == 200 and ok.json()["title"] == "A real title"
    finally:
        os.environ.pop("SDK_ALLOW_UNAUTHENTICATED", None)


# ------------------------------------------------------------------ ENG-12 / TEN-03: atomic Tavily meter
def test_concurrent_metering_never_overshoots_the_budget(svc, monkeypatch):
    from lib import tavily_meter
    monkeypatch.setenv("TAVILY_MONTHLY_BUDGET", "7")
    results, errors = [], []

    def worker():
        try:
            for _ in range(5):
                results.append(tavily_meter.meter("s")["allowed"])
        except Exception as e:           # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(6)]       # 30 attempts against a budget of 7
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    assert results.count(True) == 7 and results.count(False) == 23
    assert tavily_meter.budget_status("s")["used"] == 7


def test_a_site_can_carry_its_own_tavily_budget(svc, monkeypatch):
    from lib import tavily_meter
    from lib.db import Site, get_session
    monkeypatch.setenv("TAVILY_MONTHLY_BUDGET", "1000")
    s = get_session()
    try:
        site = s.query(Site).filter_by(slug="s").one()
        site.settings = {**(site.settings or {}), "budget": {"tavily_monthly": 2}}
        s.commit()
    finally:
        s.close()
    assert [tavily_meter.meter("s")["allowed"] for _ in range(4)] == [True, True, False, False]
    assert tavily_meter.budget_status("s")["budget"] == 2


def test_concurrent_site_creation_does_not_blow_up(svc):
    from lib.db import Site, get_session
    from lib.store import get_or_create_site
    errors, ids = [], []

    def worker():
        s = get_session()
        try:
            ids.append(get_or_create_site(s, "raced-site").id)
        except Exception as e:
            errors.append(e)
        finally:
            s.close()

    ts = [threading.Thread(target=worker) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors and len(set(ids)) == 1


# ------------------------------------------------------------------ TEN-08: one-call provisioning
def test_provisioning_creates_the_site_and_a_one_time_key_and_is_idempotent(svc, monkeypatch):
    monkeypatch.setattr(svc, "site_health", lambda slug, **k: {"ok": True})
    out = svc.provision_site("new-client", name="New Client", site_type="custom", base_url="https://new.test",
                             settings={"posting_frequency": "weekly"})
    assert "error" not in out and out["created"] is True
    assert out["key"]["key"].startswith("cfte_") and out["key"]["scopes"] == ["read", "write"]
    assert out["health"] == {"ok": True}
    assert any("only once" in t for t in out["next"])
    # a re-run does NOT mint a second plaintext key
    again = svc.provision_site("new-client", base_url="https://new.test")
    assert again["created"] is False and again["key"] is None and "already has" in again["key_note"]
    # ...unless asked to
    rotated = svc.provision_site("new-client", rotate_key=True)
    assert rotated["key"]["key"] != out["key"]["key"]


def test_provisioning_validates_and_lists_what_a_human_still_has_to_do(svc, monkeypatch):
    monkeypatch.setattr(svc, "site_health", lambda slug, **k: {"ok": False})
    assert "invalid site slug" in svc.provision_site("Bad Slug")["error"]
    assert "invalid site_type" in svc.provision_site("ok-slug", site_type="ghost")["error"]
    assert "invalid base_url" in svc.provision_site("ok-slug", base_url="ftp://x")["error"]
    wp = svc.provision_site("wp-client", site_type="wordpress", base_url="https://wp.test")
    assert any("application password" in t for t in wp["next"])
    done = svc.provision_site("wp-client-2", site_type="wordpress", base_url="https://wp2.test",
                              settings={"wp": {"username": "ed", "app_password": "abcd efgh"}})
    assert not any("application password" in t for t in done["next"])
    # the secret was stored but is not echoed back
    assert "abcd efgh" not in str(done)


def test_a_site_key_cannot_provision(svc):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sdk.server import router
    k = svc.provision_site("tenant-a", base_url="https://a.test", check_health=False)["key"]["key"]
    app = FastAPI()
    app.include_router(router)
    import os
    os.environ["SDK_MASTER_KEY"] = "platform-key"
    try:
        c = TestClient(app)
        assert c.post("/sdk/v1/provision", json={"slug": "tenant-b"}, headers={"X-Site-Key": k}).status_code == 403
        ok = c.post("/sdk/v1/provision", json={"slug": "tenant-b", "check_health": False},
                    headers={"X-Site-Key": "platform-key"})
        assert ok.status_code == 200 and ok.json()["key"]["key"].startswith("cfte_")
    finally:
        os.environ.pop("SDK_MASTER_KEY", None)


# ------------------------------------------------------------------ TEN-06: post-id WordPress ops use the named site
def test_post_id_wordpress_ops_use_the_named_sites_credentials_not_the_process_env(svc, monkeypatch):
    seen = []

    class FakeConn:
        def __init__(self, cfg):
            seen.append(cfg)

        def get_post(self, post_id):
            return {"id": post_id}

    monkeypatch.setattr("lib.wordpress.WordPressConnector", FakeConn)
    monkeypatch.setenv("WP_BASE_URL", "https://env-wp.test")
    monkeypatch.setenv("WP_USERNAME", "env-user")
    monkeypatch.setenv("WP_APP_PASSWORD", "env-pass")
    svc.upsert_site("wpa", "A", "wordpress", "https://a.test",
                    {"wp": {"base_url": "https://a-wp.test", "username": "a-user", "app_password": "a-pass"}})
    assert svc.wp_post(7, site_slug="wpa") == {"id": 7}
    assert seen[-1].base_url == "https://a-wp.test" and seen[-1].username == "a-user"
    assert "error" in svc.wp_post(7, site_slug="nope")


def test_in_shared_mode_a_post_id_op_without_a_site_is_refused_not_sent_to_the_env_wordpress(svc, monkeypatch):
    monkeypatch.setenv("TENANCY_MODE", "shared")
    monkeypatch.setenv("WP_BASE_URL", "https://env-wp.test")
    monkeypatch.setenv("WP_USERNAME", "u")
    monkeypatch.setenv("WP_APP_PASSWORD", "p")
    out = svc.wp_post(7)
    assert "site_slug is required" in out["error"]
    assert "site_slug is required" in svc.elementor_available()["error"]
    assert "site_slug is required" in svc.elementor_document(7)["error"]


# ------------------------------------------------------------------ OPS-01: the audit trail names the actor
def test_audit_rows_record_which_key_acted(svc):
    from lib.actor import set_actor
    from lib.db import AuditLog, get_session
    aid = svc.submit_article("s", keyword="who did it")["id"]
    token = set_actor("site:s/prod-key")
    try:
        svc.approve_article(aid, False, note="needs work", via="sdk")
    finally:
        set_actor("")
    svc.approve_article(aid, False, note="again", via="cli")           # outside a request: no actor
    s = get_session()
    try:
        rows = s.query(AuditLog).filter_by(article_id=aid, action="article.needs_review").order_by(AuditLog.id).all()
        assert rows[0].payload["actor"] == "site:s/prod-key" and rows[0].payload["note"] == "needs work"
        assert "actor" not in rows[1].payload
    finally:
        s.close()


def test_the_rest_layer_publishes_the_caller_to_the_audit_layer(svc, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from lib.db import AuditLog, get_session
    from sdk.server import router
    key = svc.provision_site("audited", check_health=False, key_scopes=["read", "write", "approve"])["key"]["key"]
    monkeypatch.setenv("SDK_MASTER_KEY", "platform-key")
    app = FastAPI()
    app.include_router(router)
    c = TestClient(app)
    aid = svc.submit_article("audited", keyword="audit me")["id"]
    assert c.post(f"/sdk/v1/articles/{aid}/approve", json={"approved": False, "note": "n"},
                  headers={"X-Site-Key": key}).status_code == 200
    s = get_session()
    try:
        row = s.query(AuditLog).filter_by(article_id=aid, action="article.needs_review").one()
        assert row.payload["actor"].startswith("site:audited/")
    finally:
        s.close()


# ------------------------------------------------------------------ PIPE-06: scheduled runs get the site's Brand DNA
def test_brand_dna_is_applied_for_the_named_or_default_site_and_fails_open(svc):
    from lib.brand_dna import apply_brand_dna_for_site, save_profile
    from lib.db import Site, get_session

    class Agent:
        def __init__(self, name):
            self.name, self.instructions = name, "Write."

    assert apply_brand_dna_for_site([Agent("x")]) in ([], ["x"])          # no saved profile: defaults at most, no crash
    s = get_session()
    try:
        site = s.query(Site).filter_by(slug="s").one()
        save_profile(s, site.id, {"pov": "first", "banned_phrases": ["synergy"]})
    finally:
        s.close()
    a, b = Agent("Brief"), Agent("Draft")
    assert apply_brand_dna_for_site([a, b], "s") == ["Brief", "Draft"]
    assert "synergy" in a.instructions and a.instructions.count("[BRAND DNA") == 1
    assert apply_brand_dna_for_site([a, b], "s") == []                    # idempotent
    c = Agent("Other")
    assert apply_brand_dna_for_site([c], "no-such-site") == [] and c.instructions == "Write."


def test_the_scheduled_pipeline_entry_point_applies_brand_dna():
    src = open("scripts/run_stage.py", encoding="utf-8").read()
    assert "apply_brand_dna_for_site([brief_agent, content_generator_agent, post_editor_agent])" in src
    assert src.index("apply_brand_dna_for_site") < src.index("asyncio.run(STAGE_HANDLERS[args.stage]())")
