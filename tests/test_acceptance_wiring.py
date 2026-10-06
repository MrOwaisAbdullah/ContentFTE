"""Phase 1A acceptance wiring: Tavily metering, SEO-provider metrics, keyword
cannibalization triage, and the per-post cost ledger at publish.

Runs against a throwaway sqlite DB; no network (SEO provider stays `off`).
"""
import importlib.util
import os

import pytest
from sqlalchemy import select

from lib import tavily_meter, store
from lib.db import Article, KeywordLedger, Site  # noqa: F401 (fixture use)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def temp_db(tmp_path):
    import lib.db as db
    old_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path / 'acc_test.db'}"
    db._engine = None
    db._SessionLocal = None
    db.init_db()
    yield db
    if db._engine is not None:
        db._engine.dispose()
    db._engine = None
    db._SessionLocal = None
    if old_url is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = old_url


# ---------------------------------------------------------------------------
# Tavily metering
# ---------------------------------------------------------------------------
def test_tavily_meter_budget_and_pause(temp_db, monkeypatch):
    monkeypatch.setenv("TAVILY_MONTHLY_BUDGET", "3")
    s = temp_db.get_session()
    try:
        site = store.get_or_create_site(s, "t")
        first = tavily_meter.check_and_increment(s, site.slug)
        assert first["allowed"] is True and first["used"] == 1
        tavily_meter.check_and_increment(s, site.slug)
        third = tavily_meter.check_and_increment(s, site.slug)
        assert third["allowed"] is True and third["used"] == 3 and third["exhausted"] is True
        # budget spent -> pause-and-flag
        over = tavily_meter.check_and_increment(s, site.slug)
        assert over["allowed"] is False
        status = tavily_meter.budget_status(site.slug)
        assert status["remaining"] == 0 and status["exhausted"] is True
    finally:
        s.close()


def test_tavily_meter_fail_open(monkeypatch):
    # with no creds/DB reachable the wrapper still allows the call
    monkeypatch.setattr(tavily_meter, "init_db", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    out = tavily_meter.meter("t")
    assert out["allowed"] is True and "error" in out


def test_search_tools_guard_present():
    src = open(os.path.join(REPO_ROOT, "tools", "search_tools.py"), encoding="utf-8").read()
    assert src.count("tavily_meter import meter") == 3


# ---------------------------------------------------------------------------
# SEO provider tool (off mode = manual fields, no network)
# ---------------------------------------------------------------------------
def test_seo_tool_off_mode_manual(temp_db, monkeypatch):
    monkeypatch.setenv("SEO_DATA_PROVIDER", "off")
    from tools.seo_tool import get_keyword_metrics
    out = get_keyword_metrics("crm software", volume=1200, difficulty=42, intent="commercial")
    assert out["status"] == "ok"
    assert out["provider"] == "off"
    assert out["data"]["volume"] == 1200
    assert out["data"]["difficulty"] == 42
    assert out["data"]["intent"] == "commercial"


def test_seo_tool_requires_keyword():
    from tools.seo_tool import get_keyword_metrics
    assert get_keyword_metrics("") ["status"] == "error"


# ---------------------------------------------------------------------------
# Cannibalization triage
# ---------------------------------------------------------------------------
def test_cannibalization_decisions(temp_db):
    from lib.ledger import upsert_keyword
    from tools.ledger_tool import check_cannibalization

    s = temp_db.get_session()
    try:
        site = store.get_or_create_site(s, "t")
        upsert_keyword(s, site.id, "email marketing tools")
    finally:
        s.close()

    assert check_cannibalization("sourdough bread", "t")["decision"] == "write"
    assert check_cannibalization("email marketing tools", "t")["decision"] == "merge"
    diff = check_cannibalization("email marketing software", "t")
    assert diff["decision"] == "differentiate"
    assert diff["with_keyword"] == "email marketing tools"

    assert check_cannibalization("", "t")["status"] == "error"


# ---------------------------------------------------------------------------
# Cost ledger at publish
# ---------------------------------------------------------------------------
def test_cost_ledger_finalize_idempotent(temp_db):
    from lib.cost_ledger import article_total, finalize, record_article_costs

    s = temp_db.get_session()
    try:
        site = store.get_or_create_site(s, "t")
        art = Article(site_id=site.id, title="P", status="approved")
        s.add(art)
        s.commit()
        s.refresh(art)
        record_article_costs(s, art.id, {"llm": 0.02, "image": 0.003})
        totals = finalize(s, art.id)
        assert totals["total_usd"] == 0.023
        # finalize again does not double the total row
        totals2 = finalize(s, art.id)
        assert totals2["total_usd"] == 0.023
        assert article_total(s, art.id)["total_usd"] == 0.023
    finally:
        s.close()


def test_publish_sets_cost_usd(temp_db):
    from lib.cost_ledger import record_article_costs
    from sdk import service

    s = temp_db.get_session()
    try:
        site = store.get_or_create_site(s, "t")
        art = Article(site_id=site.id, title="P", status="approved")
        s.add(art)
        s.commit()
        art_id = art.id
        record_article_costs(s, art_id, {"llm": 0.05, "image": 0.002})
    finally:
        s.close()

    out = service.publish_article(art_id, mode="auto")
    assert out["status"] == "published"
    assert out["cost_usd"] == 0.052


# ---------------------------------------------------------------------------
# Brief agent wiring
# ---------------------------------------------------------------------------
def test_brief_agent_has_acceptance_tools():
    from blog_agent.blog_agents import brief_agent

    names = {
        getattr(t, "name", None) or getattr(t, "tool_name", None)
        for t in brief_agent.tools
    }
    assert "get_keyword_metrics_tool" in names
    assert "check_cannibalization_tool" in names
    txt = brief_agent.instructions
    assert "get_keyword_metrics_tool" in txt
    assert "check_cannibalization_tool" in txt
