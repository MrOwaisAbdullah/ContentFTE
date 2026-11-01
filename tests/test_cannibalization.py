"""Plan SEO-11: cannibalization detection that would have caught the live site's clusters."""
from __future__ import annotations

import pytest

from lib.ledger import _norm, overlap_ratio, upsert_keyword


def _r(a: str, b: str) -> float:
    return overlap_ratio(_norm(a), _norm(b))


def test_plurals_and_inflections_compare_equal():
    assert _norm("AI agents") == _norm("ai agent")
    assert _norm("building servers") == _norm("build server")
    assert _norm("MCP security") != _norm("MCP servers")


def test_a_single_shared_word_is_not_a_collision():
    # Used to be flagged at 1.0: "mcp" ⊂ any row mentioning mcp.
    assert _r("mcp", "mcp server security best practices") == 0.0
    assert _r("agents", "ai agents vs automations") == 0.0


def test_identical_single_term_still_collides():
    assert _r("agents", "agent") == 1.0


def test_near_duplicates_from_the_live_site_are_caught():
    # real slugs from sitemap/blogs.xml that the ledger check could not see
    pairs = [
        ("Build autonomous AI employees in Python using MCP",
         "Build practical autonomous AI employees using MCP and Python"),
        ("Solving the MCP context bottleneck", "Solving MCP context bloat"),
        ("How to run DeepSeek and Gemini models inside the OpenAI Agents SDK",
         "Running DeepSeek and Gemini in the OpenAI Agents SDK"),
        ("Best AI automation development firms in 2026", "Top AI automation development firms 2026"),
    ]
    for a, b in pairs:
        assert _r(a, b) >= 0.6, (a, b, _r(a, b))


def test_unrelated_topics_do_not_collide():
    assert _r("sourdough bread", "email marketing tools") == 0.0
    assert _r("Gemini 3 Pro image generation", "Plaud Note smart recorder review") == 0.0


def test_long_tail_that_fully_covers_a_head_term_is_flagged_but_capped_below_merge():
    r = _r("complete guide to ai agent orchestration frameworks and patterns", "ai agent orchestration")
    assert 0.6 <= r <= 0.7          # differentiate, never auto-merge


def test_existing_decision_bands_are_preserved():
    assert _r("email marketing software", "email marketing tools") == pytest.approx(2 / 3, abs=0.01)
    assert _r("email marketing tools", "email marketing tools") == 1.0


# ---------------------------------------------------------------- DB-backed
@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'cannibal.db'}")
    import lib.db as dbm
    if dbm._engine is not None:
        dbm._engine.dispose()
    dbm._engine = None
    dbm._SessionLocal = None
    dbm.init_db()
    yield dbm
    if dbm._engine is not None:
        dbm._engine.dispose()
    dbm._engine = None
    dbm._SessionLocal = None


def test_ranking_keywords_are_protected_and_lost_ones_are_not(db):
    from lib.db import KeywordLedger, Site
    from lib.ledger import check_cannibalization
    s = db.get_session()
    try:
        site = Site(slug="c", name="C")
        s.add(site)
        s.commit()
        won = upsert_keyword(s, site.id, "openai agents sdk tutorial")
        won.status = "won"
        lost = upsert_keyword(s, site.id, "spec driven development guide")
        lost.status = "lost"
        s.commit()
        hit = check_cannibalization(s, site.id, "openai agents sdk tutorials for beginners")
        assert hit["overlap"] and hit["with_keyword"] == "openai agents sdk tutorial" \
            and hit["source"] == "ledger"
        assert not check_cannibalization(s, site.id, "spec driven development guide")["overlap"]
    finally:
        s.close()


def test_existing_article_titles_count_even_when_not_in_the_ledger(db):
    from lib.db import Site
    from lib.ledger import check_cannibalization
    s = db.get_session()
    try:
        site = Site(slug="c2", name="C2")
        s.add(site)
        s.commit()
        res = check_cannibalization(
            s, site.id, "solving mcp context bloat",
            titles=["Solving the MCP Context Bottleneck", "Plaud Note review"])
        assert res["overlap"] is True and res["source"] == "article"
        assert res["with_keyword"] == "Solving the MCP Context Bottleneck"
        assert check_cannibalization(s, site.id, "sourdough bread", titles=["Plaud Note review"])["overlap"] is False
    finally:
        s.close()
