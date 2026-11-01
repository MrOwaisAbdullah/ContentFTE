"""Plan ENG-08 / ENG-09 / TEN-03: tenant data never widens silently, logs are site-filterable, and a
site cannot spend past its monthly cap."""
from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sdk import keys
from sdk.server import router

MASTER = "master-secret-key"


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'tenant.db'}")
    monkeypatch.setenv("SDK_MASTER_KEY", MASTER)
    monkeypatch.delenv("SDK_ALLOW_UNAUTHENTICATED", raising=False)
    monkeypatch.setenv("TENANCY_MODE", "isolated")
    import lib.db as db
    if db._engine is not None:
        db._engine.dispose()
    db._engine = None
    db._SessionLocal = None
    from sdk import service
    service.init()
    app = FastAPI()
    app.include_router(router)
    w = {"service": service, "client": TestClient(app, raise_server_exceptions=False), "ids": {}}
    from lib.db import Article, get_session
    for slug in ("site-a", "site-b"):
        service.upsert_site(slug, slug.upper(), "custom", f"https://{slug}.test", {"require_approval": False})
        art = service.submit_article(slug, keyword=f"{slug} kw")
        s = get_session()
        try:
            a = s.get(Article, art["id"])
            a.content_md, a.status = f"Body {slug}.", "drafted"
            s.commit()
            w["ids"][slug] = a.id
        finally:
            s.close()
        w[f"key_{slug}"] = keys.create_site_key(slug, label=slug, scopes=["read", "write"])["key"]
    yield w
    if db._engine is not None:
        db._engine.dispose()
    db._engine = None
    db._SessionLocal = None


def H(k):
    return {"X-Site-Key": k}


# ------------------------------------------------------------------ no silent widening (ENG-08)
def test_an_unknown_site_slug_is_an_error_everywhere_never_all_tenants(world):
    svc = world["service"]
    calls = [
        lambda: svc.list_brain_entries("nope"),
        lambda: svc.get_brain_notes("anything", "nope"),
        lambda: svc.create_brain_entry("nope", "voice", "t", [], "c"),
        lambda: svc.mine_feedback("nope"),
        lambda: svc.list_review_feedback("nope"),
        lambda: svc.get_spend_summary("nope"),
        lambda: svc.list_logs(site_slug="nope"),
    ]
    for i, call in enumerate(calls):
        out = call()
        assert "error" in out and "nope" in out["error"], (i, out)


def test_a_typod_slug_no_longer_creates_a_global_brain_entry(world):
    svc = world["service"]
    assert "error" in svc.create_brain_entry("site-typo", "voice", "T", [], "secret story")
    assert svc.list_brain_entries()["count"] == 0


def test_shared_mode_requires_a_site_for_tenant_content(world, monkeypatch):
    svc = world["service"]
    monkeypatch.setenv("TENANCY_MODE", "shared")
    for call in (lambda: svc.list_brain_entries(), lambda: svc.get_brain_notes("x"),
                 lambda: svc.mine_feedback(), lambda: svc.list_review_feedback(),
                 lambda: svc.create_brain_entry("", "voice", "T", [], "c")):
        out = call()
        assert "error" in out and "site_slug is required" in out["error"]
    # ...while a named site works, and the platform-wide spend/log views stay available
    assert "error" not in svc.list_brain_entries("site-a")
    assert "error" not in svc.get_spend_summary("")
    assert "error" not in svc.list_logs()


def test_single_site_engines_still_accept_an_empty_slug(world):
    svc = world["service"]
    assert "error" not in svc.list_brain_entries()
    assert "error" not in svc.list_review_feedback()


def test_brain_notes_never_cross_tenants_in_shared_mode(world, monkeypatch):
    svc = world["service"]
    svc.create_brain_entry("site-a", "voice", "A war story about kubernetes", ["kubernetes"], "A's private lesson")
    svc.create_brain_entry("site-b", "voice", "B war story about kubernetes", ["kubernetes"], "B's private lesson")
    svc.create_brain_entry("", "voice", "Owner story about kubernetes", ["kubernetes"], "owner's lesson")  # global row

    monkeypatch.setenv("TENANCY_MODE", "shared")
    notes = svc.get_brain_notes("kubernetes", "site-a")
    titles = {e["title"] for e in notes["entries"]}
    assert titles == {"A war story about kubernetes"}                     # not B, not the owner's global row
    assert "B's private lesson" not in notes["text"] and "owner's lesson" not in notes["text"]
    assert not any(e.get("source_file") for e in notes["entries"])         # repo brain/*.md excluded too


def test_brain_notes_in_isolated_mode_still_include_the_operators_global_notes(world, monkeypatch):
    svc = world["service"]
    svc.create_brain_entry("site-a", "voice", "A story about kubernetes", ["kubernetes"], "a")
    svc.create_brain_entry("", "voice", "Owner story about kubernetes", ["kubernetes"], "owner")
    monkeypatch.setenv("TENANCY_MODE", "isolated")
    titles = {e["title"] for e in svc.get_brain_notes("kubernetes", "site-a")["entries"]}
    assert {"A story about kubernetes", "Owner story about kubernetes"} <= titles


# ------------------------------------------------------------------ site-filtered logs (ENG-09)
def _approve(world, slug):
    return world["service"].approve_article(world["ids"][slug], True, force=True)


def _spend(world, slug, usd):
    from lib.cost_ledger import record_cost
    from lib.db import get_session
    s = get_session()
    try:
        record_cost(s, world["ids"][slug], "llm", usd)
    finally:
        s.close()


def test_logs_can_be_filtered_to_one_site(world):
    _approve(world, "site-a")
    _approve(world, "site-b")
    _spend(world, "site-a", 0.25)
    _spend(world, "site-b", 0.75)
    svc = world["service"]
    a = svc.list_logs(site_slug="site-a")
    assert a["audit"]
    # site-a's own rows include ones with no article (e.g. its key creation) -- never site-b's
    assert {x["article_id"] for x in a["audit"]} <= {world["ids"]["site-a"], None}
    assert "site-b" not in repr(a["audit"])
    assert [c["amount_usd"] for c in a["costs"]] == [0.25]
    both = svc.list_logs()
    assert {x["article_id"] for x in both["audit"] if x["article_id"]} >= {world["ids"]["site-a"], world["ids"]["site-b"]}


def test_a_site_key_sees_only_its_own_logs_over_rest(world):
    _approve(world, "site-a")
    _approve(world, "site-b")
    c = world["client"]
    own = c.get("/sdk/v1/logs", headers=H(world["key_site-a"]))
    assert own.status_code == 200
    assert {x["article_id"] for x in own.json()["audit"]} <= {world["ids"]["site-a"], None}
    assert world["ids"]["site-b"] not in {x["article_id"] for x in own.json()["audit"]}
    assert c.get("/sdk/v1/logs?site_slug=site-b", headers=H(world["key_site-a"])).status_code == 403
    assert c.get("/sdk/v1/logs", headers=H(MASTER)).status_code == 200


def test_stage_history_stays_platform_only(world):
    assert world["client"].get("/sdk/v1/stages", headers=H(world["key_site-a"])).status_code == 403


# ------------------------------------------------------------------ monthly spend cap (TEN-03)
def _cap(world, slug, usd):
    world["service"].upsert_site(slug, settings={"budget": {"monthly_usd": usd}})


async def _never_called(_brief):
    raise AssertionError("generation must not run once the cap is reached")


def test_generation_is_refused_once_the_monthly_cap_is_reached(world):
    svc = world["service"]
    _cap(world, "site-a", 1.00)
    _spend(world, "site-a", 1.00)
    aid = svc.submit_article("site-a", keyword="over budget")["id"]
    out = asyncio.run(svc.generate_content(aid, generate_fn=_never_called))
    assert out["code"] == "budget_exceeded" and "monthly spend cap" in out["error"]
    assert out["budget"]["exceeded"] is True and out["budget"]["cap_usd"] == 1.0


def test_images_are_refused_over_the_cap_too(world):
    svc = world["service"]
    _cap(world, "site-a", 0.50)
    _spend(world, "site-a", 0.60)
    assert svc.stage_images(world["ids"]["site-a"])["code"] == "budget_exceeded"
    assert svc.regenerate_article_image(world["ids"]["site-a"], "x.png")["code"] == "budget_exceeded"


def test_the_cap_is_per_site_and_no_cap_means_unlimited(world):
    svc = world["service"]
    _cap(world, "site-a", 0.10)
    _spend(world, "site-a", 5.00)
    _spend(world, "site-b", 5.00)                                # site-b has no cap
    assert svc.budget_status.__name__                            # exported helper exists
    from lib.db import Site, get_session
    s = get_session()
    try:
        a = svc.budget_status(s, s.query(Site).filter_by(slug="site-a").one())
        b = svc.budget_status(s, s.query(Site).filter_by(slug="site-b").one())
    finally:
        s.close()
    assert a["exceeded"] is True and a["remaining_usd"] == 0.0
    assert b["exceeded"] is False and b["cap_usd"] is None and b["remaining_usd"] is None


def test_under_the_cap_is_not_blocked_and_garbage_caps_are_ignored(world):
    svc = world["service"]
    from lib.db import Site, get_session
    _cap(world, "site-a", 10.0)
    _spend(world, "site-a", 1.0)
    s = get_session()
    try:
        site = s.query(Site).filter_by(slug="site-a").one()
        assert svc.budget_status(s, site)["exceeded"] is False
        site.settings = {**site.settings, "budget": {"monthly_usd": "lots"}}
        s.commit()
        assert svc.budget_status(s, site)["cap_usd"] is None      # unparseable => no cap, not a crash
    finally:
        s.close()


def test_last_months_spend_does_not_count(world):
    from datetime import datetime, timedelta, timezone
    from lib.db import CostLedger, get_session
    svc = world["service"]
    _cap(world, "site-a", 1.0)
    _spend(world, "site-a", 0.5)
    s = get_session()
    try:
        old = CostLedger(article_id=world["ids"]["site-a"], site_id=None, kind="llm", amount_usd=99.0,
                         created_at=datetime.now(timezone.utc) - timedelta(days=45))
        s.add(old)
        s.commit()
    finally:
        s.close()
    s = get_session()
    try:
        from lib.db import Site
        assert svc.budget_status(s, s.query(Site).filter_by(slug="site-a").one())["mtd_usd"] == 0.5
    finally:
        s.close()


def test_rest_maps_the_cap_to_402_and_spend_summary_shows_the_budget(world):
    _cap(world, "site-a", 1.0)
    _spend(world, "site-a", 1.0)
    c = world["client"]
    aid = world["ids"]["site-a"]
    r = c.post(f"/sdk/v1/articles/{aid}/stage-images", headers=H(MASTER))
    assert r.status_code == 402 and "monthly spend cap" in r.json()["detail"]
    summary = c.get("/sdk/v1/spend/summary?site_slug=site-a", headers=H(MASTER)).json()
    assert summary["budget"]["exceeded"] is True and summary["mtd_usd"] == 1.0
    # another tenant is unaffected
    assert c.get("/sdk/v1/spend/summary?site_slug=site-b", headers=H(MASTER)).json()["budget"]["exceeded"] is False
