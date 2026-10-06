"""§5.10-1 decay → refresh briefs, §5.16 ranking write-back, and §5.8/§24
monthly AI share-of-voice.

Pure decision logic is tested directly; the decay job + share-of-voice store
run against a throwaway sqlite DB (GSC is injected, never called).
"""
import importlib.util
import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from lib import decay, share_of_voice

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_decay_job():
    path = os.path.join(REPO_ROOT, "scripts", "decay_job.py")
    spec = importlib.util.spec_from_file_location("decay_job_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Decay detection + classification
# ---------------------------------------------------------------------------
def test_click_decay_and_no_baseline():
    assert decay.click_decay(70, 100) == pytest.approx(0.30)
    assert decay.click_decay(0, 0) is None
    assert decay.click_decay(5, None) is None


def test_detect_decay_threshold():
    assert decay.detect_decay(60, 100)["decaying"] is True       # 40% > 30%
    assert decay.detect_decay(80, 100)["decaying"] is False      # 20%
    no_base = decay.detect_decay(10, 0)
    assert no_base["decaying"] is False and no_base["reason"] == "no_baseline"


def test_classify_refresh_modes():
    assert decay.classify_refresh(0.10) == decay.NONE
    assert decay.classify_refresh(0.35) == decay.MINOR
    assert decay.classify_refresh(0.60) == decay.MAJOR
    assert decay.classify_refresh(0.35, intent_shift=True) == decay.MAJOR
    assert decay.classify_refresh(0.10, intent_shift=True) == decay.MAJOR
    assert decay.classify_refresh(0.35, age_days=400) == decay.MAJOR


def test_build_refresh_brief_actions():
    major = decay.build_refresh_brief("/blog/x", "X", "kw", 0.6, decay.MAJOR)
    assert any("301" in a for a in major["actions"])
    assert major["reference"].endswith("refresh-decay.md")
    minor = decay.build_refresh_brief("/blog/x", "X", "kw", 0.35, decay.MINOR)
    assert all("301" not in a for a in minor["actions"])
    with pytest.raises(ValueError):
        decay.build_refresh_brief("/blog/x", "X", "kw", 0.6, "bogus")


def test_plan_refresh_briefs_filters_and_modes():
    pages = [
        {"url": "/blog/a", "title": "A", "keyword": "a", "current_clicks": 40, "prior_clicks": 100},   # 60% -> major
        {"url": "/blog/b", "title": "B", "keyword": "b", "current_clicks": 65, "prior_clicks": 100},   # 35% -> minor
        {"url": "/blog/c", "title": "C", "keyword": "c", "current_clicks": 95, "prior_clicks": 100},   # stable -> skip
    ]
    briefs = decay.plan_refresh_briefs(pages)
    modes = {b["page_url"]: b["mode"] for b in briefs}
    assert modes == {"/blog/a": decay.MAJOR, "/blog/b": decay.MINOR}
    assert briefs[0]["addressable_queries"] == []


def test_plan_refresh_briefs_intent_shift_forces_brief():
    pages = [{"url": "/blog/x", "title": "X", "keyword": "x",
              "current_clicks": 95, "prior_clicks": 100, "intent_shift": True}]
    briefs = decay.plan_refresh_briefs(pages)
    assert len(briefs) == 1 and briefs[0]["mode"] == decay.MAJOR


# ---------------------------------------------------------------------------
# Share of voice (pure)
# ---------------------------------------------------------------------------
def test_category_prompts_deterministic():
    p = share_of_voice.category_prompts("crm", count=3)
    assert p == ["best crm tools", "what is the best crm software",
                 "crm tools for small business"]


def test_share_of_voice_pct_and_summarize():
    assert share_of_voice.share_of_voice_pct(0, 0) == 0.0
    assert share_of_voice.share_of_voice_pct(2, 4) == 50.0
    records = [
        {"month": "2026-09", "platform": "chatgpt", "prompt": "q1", "cited": True},
        {"month": "2026-09", "platform": "chatgpt", "prompt": "q2", "cited": False},
        {"month": "2026-10", "platform": "gemini", "prompt": "q1", "cited": True},
    ]
    s = share_of_voice.summarize(records)
    assert s["runs"] == 3
    assert s["overall_pct"] == 66.7
    assert s["by_month"]["2026-09"]["pct"] == 50.0
    assert s["by_month"]["2026-10"]["pct"] == 100.0
    assert s["by_platform"]["chatgpt"]["pct"] == 50.0


def test_monthly_share_of_voice_scopes_month():
    out = share_of_voice.monthly_share_of_voice(
        "2026-10", [{"platform": "chatgpt", "prompt": "q", "cited": True}])
    assert out["by_month"]["2026-10"]["pct"] == 100.0


# ---------------------------------------------------------------------------
# DB-backed: share-of-voice store + the decay job
# ---------------------------------------------------------------------------
@pytest.fixture
def temp_db(tmp_path):
    import lib.db as db
    db_file = tmp_path / "decay_test.db"
    old_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
    db._engine = None
    db._SessionLocal = None
    db.init_db()
    yield db
    # Windows: dispose the engine BEFORE deleting the file.
    if db._engine is not None:
        db._engine.dispose()
    db._engine = None
    db._SessionLocal = None
    if old_url is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = old_url


def test_share_of_voice_store_roundtrip(temp_db):
    from lib.db import Site
    s = temp_db.get_session()
    try:
        site = Site(slug="t", name="T")
        s.add(site)
        s.commit()
        share_of_voice.record_share_of_voice(s, site.id, "2026-10", [
            {"platform": "chatgpt", "prompt": "best x", "cited": True},
            {"platform": "gemini", "prompt": "best x", "cited": False},
        ])
        summary = share_of_voice.load_summary(s, site.id)
        assert summary["overall_pct"] == 50.0
        assert summary["runs"] == 2
    finally:
        s.close()


def test_decay_job_writes_brief_and_marks_lost(temp_db):
    from lib.db import Article, AuditLog, KeywordLedger, Site

    job = _load_decay_job()
    s = temp_db.get_session()
    try:
        site = Site(slug="t", name="T", base_url="https://example.com")
        s.add(site)
        s.commit()
        kw = KeywordLedger(site_id=site.id, keyword="decaying kw", status="published")
        s.add(kw)
        s.commit()
        art = Article(site_id=site.id, keyword_id=kw.id, title="Decaying",
                      slug="decaying", status="published")
        s.add(art)
        s.commit()

        calls = {"n": 0}

        def clicks_decay(url, start, end):
            calls["n"] += 1
            # collect_pages calls current window first, then prior window.
            return 30 if calls["n"] % 2 == 1 else 100

        res = job.run(dry_run=False, site_slug="t", clicks_fn=clicks_decay, session=s)
        assert res["status"] == "ok"
        assert res["refresh_count"] == 1
        assert res["refresh_briefs"][0]["mode"] == decay.MAJOR  # 70% decay

        s.refresh(kw)
        assert kw.status == "lost"
        audit = list(s.execute(select(AuditLog)).scalars())
        assert any(a.action == "refresh_brief" for a in audit)
    finally:
        s.close()


def test_decay_job_dry_run_writes_nothing(temp_db):
    from lib.db import Article, AuditLog, KeywordLedger, Site
    job = _load_decay_job()
    s = temp_db.get_session()
    try:
        site = Site(slug="t", name="T", base_url="https://example.com")
        s.add(site)
        s.commit()
        kw = KeywordLedger(site_id=site.id, keyword="kw", status="published")
        s.add(kw)
        s.commit()
        s.add(Article(site_id=site.id, keyword_id=kw.id, title="X", slug="x",
                      status="published"))
        s.commit()
        calls = {"n": 0}

        def clicks(url, start, end):
            calls["n"] += 1
            return 10 if calls["n"] % 2 == 1 else 100

        res = job.run(dry_run=True, site_slug="t", clicks_fn=clicks, session=s)
        assert res["refresh_count"] == 1
        s.refresh(kw)
        assert kw.status == "published"  # unchanged under dry-run
        assert list(s.execute(select(AuditLog)).scalars()) == []
    finally:
        s.close()


# ---------------------------------------------------------------------------
# Scheduling wiring (static — avoids importing the heavy run_stage module)
# ---------------------------------------------------------------------------
def _read(rel):
    with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as f:
        return f.read()


def test_run_stage_registers_decay_stage():
    src = _read(os.path.join("scripts", "run_stage.py"))
    assert '"decay": run_decay' in src
    assert "async def run_decay" in src


def test_pipeline_workflow_schedules_decay_monthly():
    wf = _read(os.path.join(".github", "workflows", "pipeline.yml"))
    assert "'0 4 1 * *'" in wf          # monthly cron
    assert "stage=decay" in wf          # resolve mapping
    assert "- decay" in wf              # workflow_dispatch option

