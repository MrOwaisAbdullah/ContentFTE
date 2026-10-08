"""Draft-agent wiring (TASKS A0): TL;DR, question-H2 AEO, offer catalog
(§5.5 max 2 mentions + 1 CTA), repurpose bundle + video-script seed."""
import json

import pytest


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch):
    import os

    workdir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           ".test-tmp-phase1")
    os.makedirs(workdir, exist_ok=True)
    db_file = os.path.join(workdir, "draft.db")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("SEO_DATA_PROVIDER", "off")
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


def test_offer_catalog_reads_brand_profile():
    from lib.brand_dna import save_profile
    from lib.db import Site, get_session
    from tools.offer_tool import get_offer_catalog

    # no site yet -> explicit error, not a crash
    assert get_offer_catalog()["status"] == "error"

    s = get_session()
    try:
        site = Site(slug="offers-site", name="Offers")
        s.add(site)
        s.commit()
        s.refresh(site)
        save_profile(s, site.id, {
            "pov": "first",
            "offers": [
                {"name": "ContentFTE Pro", "description": "AI SEO content engine",
                 "url": "https://example.com/pro", "cta": "Start free"},
                "Legacy Plain Offer",
            ],
        })
    finally:
        s.close()

    cat = get_offer_catalog()
    assert cat["status"] == "ok"
    assert cat["limits"] == {"max_mentions": 2, "max_ctas": 1}
    names = [o["name"] for o in cat["offers"]]
    assert names == ["ContentFTE Pro", "Legacy Plain Offer"]
    assert cat["offers"][0]["url"] == "https://example.com/pro"

    # unknown slug -> error
    assert get_offer_catalog("nope")["status"] == "error"

    # profile without offers -> empty list (mention nothing, never invent)
    s = get_session()
    try:
        from lib.db import Site as S
        site2 = S(slug="bare-site", name="Bare")
        s.add(site2)
        s.commit()
    finally:
        s.close()
    bare = get_offer_catalog("bare-site")
    assert bare["status"] == "ok" and bare["offers"] == []


def test_generator_wired_for_tldr_offers_and_repurpose():
    from blog_agent.blog_agents import content_generator_agent

    tool_names = {t.name for t in content_generator_agent.tools}
    assert "get_offer_catalog_tool" in tool_names

    instr = content_generator_agent.instructions
    for marker in ("TL;DR", "40\u201360 word direct answer", "Question-form H2s",
                   "Offer catalog mentions", "AT MOST 2 in-body mentions",
                   "AT MOST 1 CTA block", "rel=\"sponsored\"",
                   "Repurpose Bundle", "Video Script Seed", "linkedin",
                   "x_thread"):
        assert marker in instr, f"generator instructions missing: {marker}"


def test_brief_agent_decides_offer_placement_and_video_seed():
    from blog_agent.blog_agents import brief_agent

    tool_names = {t.name for t in brief_agent.tools}
    assert "get_offer_catalog_tool" in tool_names

    instr = brief_agent.instructions
    for marker in ("Offer placement (5.5)", "natural in-body mentions",
                   "1 CTA block", "Video Script Seed", "3 bullet talking points"):
        assert marker in instr, f"brief instructions missing: {marker}"


def test_content_row_carries_repurpose_fields():
    import importlib

    run_stage = importlib.import_module("scripts.run_stage")

    assert run_stage._GENERATED_POSTS_FIELDS[-2:] == ["Repurpose Bundle",
                                                      "Video Script Seed"]
    values = run_stage._content_row_values({
        "Title": "T",
        "Generated Content": "body",
        "FAQs": [{"question": "q", "answer": "a"}],
        "Quality Score": "92",
        "Summary": "s",
        "Repurpose Bundle": {"linkedin": "li", "x_thread": ["a", "b"]},
        "Video Script Seed": {"title": "vt", "talking_points": ["1", "2", "3"]},
    }, "T")
    assert set(values) == set(run_stage._GENERATED_POSTS_FIELDS)
    # dict fields are stored as JSON strings, not Python reprs
    bundle = json.loads(values["Repurpose Bundle"])
    assert bundle["linkedin"] == "li" and bundle["x_thread"] == ["a", "b"]
    seed = json.loads(values["Video Script Seed"])
    assert seed["talking_points"] == ["1", "2", "3"]
    # missing fields degrade to empty strings, never "None"
    empty = run_stage._content_row_values({"Title": "T2"}, "T2")
    assert empty["Repurpose Bundle"] == "" and empty["Video Script Seed"] == ""


def test_generator_emits_sources_box_at_end():
    from blog_agent.blog_agents import content_generator_agent

    instr = content_generator_agent.instructions
    # §5.4: article ENDS with a Sources box (title + publisher + link)
    assert "\"## Sources\" box" in instr
    assert "- [Title](URL) (Publisher)" in instr
    assert 'avoiding separate "Sources"' not in instr  # old ban removed
    # Related Posts ban stays
    assert "NEVER add a \"Related Posts\"" in instr


def test_eval_agent_gate_ordering_and_aeo_checklist():
    from blog_agent.blog_agents import content_evaluation_agent

    instr = content_evaluation_agent.instructions
    # §5.3 ordering: fact-check gate runs BEFORE eval, never replaced by it
    assert "Gate ordering" in instr
    assert "ALREADY passed the deterministic fact-check gate" in instr
    assert "Never evaluate a draft whose gate failed" in instr
    assert "lib/eval_gate.check_gate" in instr
    # §5.7 AEO checklist scored by the eval agent
    assert "AEO checklist" in instr
    assert "caps `seo` at 79" in instr
    assert "TL;DR" in instr and "Sources" in instr
