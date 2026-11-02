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



# ---------------------------------------------------------------------------
# Plan SEO-03: a failed Search Console query is NOT "0 clicks"
# ---------------------------------------------------------------------------
def _seed_one_published(temp_db, slug="t", base="https://example.com", meta=None):
    from lib.db import Article, KeywordLedger, Site
    s = temp_db.get_session()
    site = Site(slug=slug, name=slug.upper(), base_url=base)
    s.add(site)
    s.commit()
    kw = KeywordLedger(site_id=site.id, keyword="kw", status="published")
    s.add(kw)
    s.commit()
    art = Article(site_id=site.id, keyword_id=kw.id, title="A", slug="a",
                  status="published", meta=meta or {})
    s.add(art)
    s.commit()
    return s, site, kw


def test_gsc_failure_on_current_window_is_skipped_not_scored_as_decay(temp_db):
    job = _load_decay_job()
    s, site, kw = _seed_one_published(temp_db)
    try:
        calls = {"n": 0}

        def flaky(url, start, end):
            calls["n"] += 1
            if calls["n"] == 1:           # current window fails
                raise RuntimeError("503 from Search Console")
            return 100                    # prior window answered

        res = job.run(dry_run=False, site_slug="t", clicks_fn=flaky, session=s)
        assert res["status"] == "ok"
        assert res["refresh_count"] == 0          # NOT a 100% "decay"
        assert res["pages_scanned"] == 0
        assert "search console error" in res["skipped"][0]["reason"]
        s.refresh(kw)
        assert kw.status == "published"            # keyword NOT flipped to lost
    finally:
        s.close()


def test_low_baseline_pages_are_skipped(temp_db):
    job = _load_decay_job()
    s, site, kw = _seed_one_published(temp_db)
    try:
        calls = {"n": 0}

        def tiny(url, start, end):
            calls["n"] += 1
            return 2 if calls["n"] % 2 == 1 else 3   # 3 -> 2 clicks = "33% decay" of noise

        res = job.run(dry_run=False, site_slug="t", clicks_fn=tiny, session=s)
        assert res["refresh_count"] == 0
        assert "too little data" in res["skipped"][0]["reason"]
    finally:
        s.close()


def test_recorded_published_url_wins_over_the_blog_slug_guess(temp_db):
    job = _load_decay_job()
    s, site, kw = _seed_one_published(
        temp_db, meta={"wp_url": "https://example.com/2026/05/a-real-permalink/"})
    try:
        seen = []

        def spy(url, start, end):
            seen.append(url)
            return 100

        job.run(dry_run=True, site_slug="t", clicks_fn=spy, session=s)
        assert set(seen) == {"https://example.com/2026/05/a-real-permalink/"}
    finally:
        s.close()


def test_default_clicks_fn_queries_the_sites_own_property(temp_db, monkeypatch):
    job = _load_decay_job()
    s, site, kw = _seed_one_published(temp_db, base="https://site-b.example")
    site.settings = {"search_console_site_url": "sc-domain:site-b.example"}
    s.commit()
    try:
        import lib.search_console as gsc
        used = []

        def fake_query(**kw_):
            used.append((kw_["site_url"], kw_["raise_on_error"]))
            return [{"clicks": 100}]

        monkeypatch.setattr(gsc, "query_search_analytics", fake_query)
        res = job.run(dry_run=True, site_slug="t", session=s)   # no clicks_fn -> real path
        assert res["status"] == "ok"
        assert used and all(u == ("sc-domain:site-b.example", True) for u in used)
    finally:
        s.close()


def test_missing_site_message_says_why(temp_db):
    from lib.db import explain_missing_site
    job = _load_decay_job()
    s = temp_db.get_session()
    try:
        res = job.run(dry_run=True, site_slug="", clicks_fn=lambda u, a, b: 0, session=s)
        assert res["status"] == "error"
        assert "no sites exist" in res["message"] and "DATABASE_URL" in res["message"]
        assert "default" not in res["message"].split("(")[0]      # old misleading wording gone
        from lib.db import Site
        s.add(Site(slug="real", name="R"))
        s.commit()
        assert "sites there: real" in explain_missing_site(s, "typo")
        assert "'typo' not found" in explain_missing_site(s, "typo")
    finally:
        s.close()


# ---------------------------------------------------------------------------
# Decision D10: REFRESH_POLICY (escalate | in_place)
# ---------------------------------------------------------------------------
def test_default_policy_is_the_original_escalating_behaviour(monkeypatch):
    monkeypatch.delenv("REFRESH_POLICY", raising=False)
    assert decay.refresh_policy() == "escalate"
    assert decay.classify_refresh(0.60) == decay.MAJOR                    # deep decay => new URL + 301
    assert decay.classify_refresh(0.35, age_days=400) == decay.MAJOR      # stale => new URL + 301
    assert decay.classify_refresh(0.35, age_days=100) == decay.MINOR


def test_in_place_policy_keeps_every_nonstructural_refresh_on_the_same_url(monkeypatch):
    monkeypatch.setenv("REFRESH_POLICY", "in_place")
    assert decay.refresh_policy() == "in_place"
    assert decay.classify_refresh(0.95) == decay.MINOR                    # even a collapse
    assert decay.classify_refresh(0.35, age_days=2000) == decay.MINOR     # even a very old page
    assert decay.classify_refresh(0.10) == decay.NONE                     # below threshold: still nothing
    assert decay.classify_refresh(None) == decay.NONE


def test_structural_problems_are_major_under_either_policy(monkeypatch):
    for policy in ("escalate", "in_place"):
        monkeypatch.setenv("REFRESH_POLICY", policy)
        assert decay.classify_refresh(0.35, intent_shift=True) == decay.MAJOR
        assert decay.classify_refresh(0.35, big_quality_gap=True) == decay.MAJOR
        assert decay.classify_refresh(0.05, intent_shift=True) == decay.MAJOR


def test_policy_value_is_forgiving_but_never_unsafe(monkeypatch):
    for raw, want in (("IN_PLACE", "in_place"), ("in-place", "in_place"), (" in_place ", "in_place"),
                      ("", "escalate"), ("nonsense", "escalate")):
        monkeypatch.setenv("REFRESH_POLICY", raw)
        assert decay.refresh_policy() == want, raw


def test_in_place_policy_changes_the_brief_the_operator_sees(monkeypatch):
    monkeypatch.setenv("REFRESH_POLICY", "in_place")
    pages = [{"url": "/blog/a", "title": "A", "keyword": "a", "current_clicks": 5, "prior_clicks": 100}]
    briefs = decay.plan_refresh_briefs(pages)
    assert len(briefs) == 1 and briefs[0]["mode"] == decay.MINOR          # 95% decay, but in place
    assert "Re-publish under a NEW URL" not in " ".join(briefs[0]["actions"])


# ---- SEO-16: seasonality and cause --------------------------------------------------------------------------------
def test_a_drop_that_repeats_last_years_is_seasonal_but_a_new_one_is_not():
    from lib.decay import is_seasonal
    # 100 -> 60 this year (-40%); the same two windows last year: 120 -> 74 (-38%) => seasonal
    assert is_seasonal(60, 100, 74, 120) is True
    # last year was flat: this drop is new
    assert is_seasonal(60, 100, 118, 120) is False
    # last year had too little data to say anything: never hide a real decline
    assert is_seasonal(60, 100, 3, 5) is False
    assert is_seasonal(60, 100, None, None) is False
    assert is_seasonal(100, 100, 80, 120) is False                # no drop this year at all


def test_cause_diagnosis_separates_rank_demand_and_click_through():
    from lib.decay import diagnose_cause
    base = dict(clicks_prior=100, impressions_prior=2000, position_prior=4.0)
    assert diagnose_cause(clicks_cur=50, impressions_cur=1900, position_cur=7.5, **base) == "rank"
    assert diagnose_cause(clicks_cur=50, impressions_cur=1000, position_cur=4.2, **base) == "demand"
    assert diagnose_cause(clicks_cur=50, impressions_cur=1950, position_cur=4.1, **base) == "ctr"
    assert diagnose_cause(clicks_cur=100, impressions_cur=2000, position_cur=4.0, **base) == "unknown"
    assert diagnose_cause(clicks_cur=1, impressions_cur=1, clicks_prior=0, impressions_prior=0) == "unknown"
    assert diagnose_cause(clicks_cur="x", impressions_cur=1, **base) == "unknown"


def test_the_decay_job_skips_seasonal_pages_only_when_yoy_is_enabled(tmp_path, monkeypatch):
    import importlib
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'y.db'}")
    monkeypatch.setenv("DECAY_USE_YOY", "1")
    monkeypatch.setenv("DECAY_MIN_PRIOR_CLICKS", "10")
    import lib.db as db
    if db._engine is not None:
        db._engine.dispose()
    db._engine = None
    db._SessionLocal = None
    from scripts import decay_job
    importlib.reload(decay_job)
    db.init_db()
    s = db.get_session()
    try:
        site = db.Site(slug="y", name="Y", base_url="https://y.test")
        s.add(site)
        s.commit()
        art = db.Article(site_id=site.id, title="T", status="published", slug="t",
                         meta={"url": "https://y.test/t"})
        s.add(art)
        s.commit()
        windows = decay_job._windows()
        year_ago_cur = windows[1] - __import__("datetime").timedelta(days=365)

        def clicks(url, start, end):
            # this year: 60 now vs 100 before; last year the same fall: 74 vs 120
            if end > year_ago_cur + __import__("datetime").timedelta(days=200):
                return 60 if end == windows[1] else 100
            return 74 if end == windows[1] - __import__("datetime").timedelta(days=365) else 120

        skipped = []
        pages = decay_job.collect_pages(s, site, clicks, skipped)
        assert pages == [] and "seasonal" in skipped[0]["reason"]
        monkeypatch.setattr(decay_job, "USE_YOY", False)
        pages = decay_job.collect_pages(s, site, clicks, [])
        assert len(pages) == 1
    finally:
        s.close()
        db._engine.dispose()
        db._engine = None
        db._SessionLocal = None


# ---- SEO-18: share-of-voice is a sample, so say how good the sample is ------------------------------------------------
def test_wilson_interval_and_confidence_grow_tighter_with_more_runs():
    from lib.share_of_voice import confidence_label, wilson_interval
    assert wilson_interval(0, 0) == (0.0, 0.0)
    lo, hi = wilson_interval(2, 7)                     # 7 runs: "29%" could be anywhere from ~8% to ~64%
    assert lo < 29 < hi and hi - lo > 40
    lo2, hi2 = wilson_interval(60, 210)                # same rate, 30x the evidence
    assert hi2 - lo2 < 15
    assert wilson_interval(10, 10)[1] == 100.0 and wilson_interval(0, 10)[0] == 0.0
    assert [confidence_label(n) for n in (7, 40, 120)] == ["low", "medium", "high"]


def test_summary_reports_interval_stability_prompts_and_competitors():
    from lib.share_of_voice import summarize
    recs = []
    for i in range(3):                                   # one prompt sampled 3 times: cited, cited, not cited
        recs.append({"month": "2026-10", "platform": "chatgpt", "prompt": "best crm", "cited": i < 2,
                     "competitors": ["hubspot.com", "Salesforce.com"]})
    recs.append({"month": "2026-10", "platform": "gemini", "prompt": "crm tools", "cited": False,
                 "competitors": ["hubspot.com"]})
    recs.append({"month": "2026-10", "platform": "gemini", "prompt": "crm tools", "cited": False,
                 "competitors": ["hubspot.com"]})
    out = summarize(recs)
    assert out["runs"] == 5 and out["overall_pct"] == 40.0 and out["confidence"] == "low"
    assert out["ci95"][0] < 40 < out["ci95"][1]
    assert out["prompts"] == 2 and out["repeated_prompts"] == 2
    assert out["stable_repeated_pct"] == 50.0           # crm tools agreed with itself; best crm did not
    assert out["competitors"][0] == {"name": "hubspot.com", "cited_in": 5, "pct": 100.0}
    assert "ci95" in out["by_month"]["2026-10"]
    assert summarize([])["overall_pct"] == 0.0


def test_prompts_come_from_real_queries_with_questions_first():
    from lib.share_of_voice import prompts_from_queries
    qs = ["crm pricing", "how to choose a crm", "crm pricing", "x", "best crm for agencies", "salesforce login"]
    out = prompts_from_queries(qs, limit=4)
    assert out == ["how to choose a crm", "best crm for agencies", "crm pricing", "salesforce login"]
    assert prompts_from_queries([], "crm", limit=3)[0] == "best crm tools"      # falls back to the scripted set
