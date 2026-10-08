"""A2 batch 4 — SERP drift job (spec §5.16 "SERP snapshots & drift
alerts"): pure comparison logic, provider force_refresh, monthly job,
stage + workflow wiring."""
from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch):
    workdir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           ".test-tmp-phase1")
    os.makedirs(workdir, exist_ok=True)
    db_file = os.path.join(workdir, "serp_drift.db")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    import lib.db as db

    if db._engine is not None:
        db._engine.dispose()
    db._engine = None
    db._SessionLocal = None
    try:
        os.remove(db_file)
    except OSError:
        pass
    db.init_db()
    yield
    if db._engine is not None:
        db._engine.dispose()
    try:
        os.remove(db_file)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Pure comparison logic
# ---------------------------------------------------------------------------
def test_normalize_url_canonicalizes():
    from lib.serp_drift import normalize_url

    assert normalize_url("http://www.Example.com/Path/?utm_source=x&q=1#frag") \
        == "https://example.com/Path?q=1"
    assert normalize_url("example.com/a/") == "https://example.com/a"
    assert normalize_url("https://example.com") == "https://example.com/"
    assert normalize_url("https://example.com/?gclid=abc") == "https://example.com/"
    assert normalize_url("") == "" and normalize_url(None) == ""


def test_serp_urls_handles_strings_and_dicts():
    from lib.serp_drift import serp_urls

    urls = serp_urls([
        "https://www.keep.test/a",
        {"url": "https://keep.test/a/"},          # dupe after normalize
        {"link": "https://two.test/b"},
        {"href": "https://three.test/c"},
        {"page_url": "https://four.test/d"},
        42,
        "",
    ])
    assert urls == ["https://keep.test/a", "https://two.test/b",
                    "https://three.test/c", "https://four.test/d"]


def test_detect_drift_threshold_and_lists():
    from lib.serp_drift import detect_drift

    base = [f"https://site.test/{i}" for i in range(5)]
    # 3 of 5 kept = 0.6 overlap -> no drift
    ok = detect_drift(base, base[:3] + ["https://new.test/x"])
    assert ok["overlap"] == 3 and ok["overlap_score"] == 0.6
    assert not ok["drifted"] and ok["churn"] == 0.4

    # 1 of 4 kept = 0.25 < 0.4 -> drifted
    bad = detect_drift(base[:4], ["https://site.test/0",
                                  "https://new.test/x"])
    assert bad["drifted"] and bad["overlap_score"] == 0.25
    assert bad["dropped"] == ["https://site.test/1", "https://site.test/2",
                              "https://site.test/3"]
    assert bad["new"] == ["https://new.test/x"]

    # no baseline -> no signal, never drifted
    none = detect_drift([], base)
    assert not none["drifted"] and none["churn"] == 0.0


# ---------------------------------------------------------------------------
# Provider force_refresh
# ---------------------------------------------------------------------------
def test_get_keyword_data_force_refresh_bypasses_and_rewrites_cache(monkeypatch):
    import lib.seo_provider as sp
    from lib.db import get_session

    monkeypatch.setenv("SEO_DATA_PROVIDER", "openseo")
    calls: list[str] = []

    def fake_fetch(keyword: str) -> dict:
        calls.append(keyword)
        return {"provider": "openseo", "keyword": keyword, "volume": 10,
                "difficulty": 5.0, "intent": "informational",
                "serp": [f"https://fresh.test/{len(calls)}"], "serp_gaps": []}

    monkeypatch.setattr(sp, "_openseo_fetch", fake_fetch)
    with get_session() as s:
        first = sp.get_keyword_data(s, "kw x")
        assert first["cache_hit"] is False and len(calls) == 1
        cached = sp.get_keyword_data(s, "kw x")
        assert cached["cache_hit"] is True and len(calls) == 1
        fresh = sp.get_keyword_data(s, "kw x", force_refresh=True)
        assert fresh["cache_hit"] is False and len(calls) == 2
        # the fresh payload replaced the cache -> next drift run's baseline
        row = sp._cache_get(s, "openseo", "kw x")
        assert row["serp"] == ["https://fresh.test/2"]


def test_get_keyword_data_off_mode_ignores_force_refresh(monkeypatch):
    import lib.seo_provider as sp
    from lib.db import get_session

    monkeypatch.setenv("SEO_DATA_PROVIDER", "off")
    with get_session() as s:
        out = sp.get_keyword_data(s, "kw", manual={"volume": 7},
                                  force_refresh=True)
    assert out["provider"] == "off" and out["volume"] == 7


# ---------------------------------------------------------------------------
# Job
# ---------------------------------------------------------------------------
def _seed(monkeypatch, *, keyword: str = "drift kw") -> int:
    monkeypatch.setenv("SEO_DATA_PROVIDER", "openseo")
    from lib.db import KeywordLedger, SeoCache, Site, get_session

    with get_session() as s:
        site = Site(slug="drift-site", name="Drift")
        s.add(site)
        s.commit()
        s.refresh(site)
        s.add(SeoCache(provider="openseo", keyword="drift kw", data={"serp": [
            "https://keep.test/a", "https://gone.test/b",
            "https://gone.test/c", "https://gone.test/d"]}))
        s.add(SeoCache(provider="openseo", keyword="stable kw",
                       data={"serp": [f"https://stable.test/{i}"
                                      for i in range(5)]}))
        s.add(SeoCache(provider="openseo", keyword="empty kw", data={}))
        s.add(KeywordLedger(site_id=site.id, keyword="drift kw"))
        s.commit()
        return site.id


def _fetch_ok(keyword: str) -> dict:
    if keyword == "drift kw":
        # 1 of 4 baseline URLs survives -> overlap 0.25 < 0.4 -> drift
        return {"serp": ["https://keep.test/a", "https://new1.test/x",
                         "https://new2.test/y", "https://new3.test/z"]}
    if keyword == "stable kw":
        return {"serp": [f"https://stable.test/{i}" for i in range(5)]}
    return {"serp": []}


def _audit_rows():
    from sqlalchemy import select
    from lib.db import AuditLog, get_session

    with get_session() as s:
        return list(s.execute(
            select(AuditLog).where(AuditLog.action == "serp.drift")
        ).scalars().all())


def _review_at(keyword: str):
    from sqlalchemy import select
    from lib.db import KeywordLedger, get_session

    with get_session() as s:
        row = s.execute(
            select(KeywordLedger).where(KeywordLedger.keyword == keyword)
        ).scalars().first()
        return None if row is None else row.review_at


def test_job_flags_drift_writes_audit_and_review(monkeypatch):
    from scripts.serp_drift_job import run

    _seed(monkeypatch)
    res = run(fetch_fn=_fetch_ok, site_slug="drift-site")
    assert res["status"] == "ok"
    assert res["checked"] == 2 and res["no_baseline"] == 1
    assert res["drift_count"] == 1
    report = res["drifted"][0]
    assert report["keyword"] == "drift kw" and report["overlap_score"] == 0.25

    audits = _audit_rows()
    assert len(audits) == 1 and audits[0].payload["keyword"] == "drift kw"
    assert _review_at("drift kw") is not None


def test_job_dry_run_writes_nothing(monkeypatch):
    from scripts.serp_drift_job import run

    _seed(monkeypatch)
    res = run(dry_run=True, fetch_fn=_fetch_ok, site_slug="drift-site")
    assert res["status"] == "ok" and res["drift_count"] == 1
    assert _audit_rows() == []
    assert _review_at("drift kw") is None


def test_job_fetch_failure_fails_open(monkeypatch):
    from scripts.serp_drift_job import run

    _seed(monkeypatch)

    def boom(keyword: str) -> dict:
        raise RuntimeError("provider down")

    res = run(fetch_fn=boom, site_slug="drift-site")
    assert res["status"] == "ok" and res["fetch_errors"] == 2
    assert res["drift_count"] == 0 and _audit_rows() == []


def test_job_skips_when_provider_off(monkeypatch):
    from scripts.serp_drift_job import run

    _seed(monkeypatch)
    monkeypatch.setenv("SEO_DATA_PROVIDER", "off")
    res = run(fetch_fn=_fetch_ok)
    assert res["status"] == "skipped" and "off" in res["message"]


def test_job_unknown_site_is_error(monkeypatch):
    from scripts.serp_drift_job import run

    _seed(monkeypatch)
    res = run(fetch_fn=_fetch_ok, site_slug="ghost")
    assert res["status"] == "error" and "not found" in res["message"]


# ---------------------------------------------------------------------------
# Scheduling wiring (static — avoids importing the heavy run_stage module)
# ---------------------------------------------------------------------------
def _read(rel: str) -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, rel), encoding="utf-8") as fh:
        return fh.read()


def test_run_stage_registers_serp_drift_stage():
    src = _read(os.path.join("scripts", "run_stage.py"))
    assert '"serp_drift": run_serp_drift' in src
    assert "async def run_serp_drift" in src


def test_pipeline_workflow_schedules_serp_drift_monthly():
    wf = _read(os.path.join(".github", "workflows", "pipeline.yml"))
    assert "'0 6 1 * *'" in wf          # monthly cron (after decay at 0 4)
    assert "stage=serp_drift" in wf     # resolve mapping
    assert "- serp_drift" in wf         # workflow_dispatch option
