"""A2 batch 2 — intent-aware word floor, fan-out queries in briefs,
win-announcement + press-release brief templates (seo-pack onpage-aeo
"length matches intent", pack brief-research)."""
from __future__ import annotations


def test_word_floor_is_intent_aware_with_env_override(monkeypatch):
    from lib.brief_templates import word_floor_for

    monkeypatch.delenv("GEN_MIN_WORDS", raising=False)
    assert word_floor_for("informational") == 900
    assert word_floor_for("commercial") == 900
    assert word_floor_for("transactional") == 400  # compact buyer-intent
    assert word_floor_for("local") == 700
    assert word_floor_for("press-release") == 400
    # unknown / empty intents never break a brief
    assert word_floor_for("") == 900
    assert word_floor_for("definitely-not-an-intent") == 900

    # operator hard override wins over every template floor
    monkeypatch.setenv("GEN_MIN_WORDS", "1234")
    assert word_floor_for("transactional") == 1234
    assert word_floor_for("informational") == 1234

    # garbage env falls back to the template floor instead of raising
    monkeypatch.setenv("GEN_MIN_WORDS", "not-a-number")
    assert word_floor_for("transactional") == 400


def test_template_aliases_and_announcement_press_release_templates():
    from lib.brief_templates import TEMPLATES, template_for, template_text

    # JEV/brief-agent vocab maps onto real templates
    assert template_for("comparison")["intent"] == "commercial"
    assert template_for("versus")["intent"] == "commercial"
    assert template_for("press")["intent"] == "press-release"
    assert template_for("pr")["intent"] == "press-release"
    assert template_for("news")["intent"] == "announcement"

    for key in ("announcement", "press-release"):
        t = TEMPLATES[key]
        assert t["required_sections"], key
        assert "3" in t["serp_gap_rule"], key  # exactly-3 SERP-gap rule
        assert any("Sources box" in s for s in t["required_sections"]), key
        assert isinstance(t["word_floor"], int) and t["word_floor"] > 0, key
        assert t["word_target"], key
        rendered = template_text(key)
        assert t["name"] in rendered and "Length: at least" in rendered

    # press-release forbids invented quotes; announcement marks [VERIFY]
    assert any("NEVER invent" in s or "never invent" in s
               for s in TEMPLATES["press-release"]["required_sections"])
    assert any("[VERIFY]" in s
               for s in TEMPLATES["announcement"]["required_sections"])

    # every template carries an explicit floor + target line
    for name, t in TEMPLATES.items():
        assert isinstance(t.get("word_floor"), int) and t["word_floor"] > 0, name
        assert t.get("word_target"), name
        assert f"at least {t['word_floor']} words" in template_text(name), name


def test_content_checks_use_intent_floor(monkeypatch):
    from sdk import service

    monkeypatch.delenv("GEN_MIN_WORDS", raising=False)
    content = " ".join(["word"] * 450)
    txn = service._content_checks(
        content=content, title="T", summary="S" * 200, faqs=[],
        brief={"intent": "transactional"})
    assert txn["words"]["pass"], txn["words"]

    # same draft on an informational brief still fails the flagship floor
    info = service._content_checks(
        content=content, title="T", summary="S" * 200, faqs=[], brief={})
    assert not info["words"]["pass"], info["words"]

    # operator override forces the hard floor on every intent
    monkeypatch.setenv("GEN_MIN_WORDS", "900")
    txn2 = service._content_checks(
        content=content, title="T", summary="S" * 200, faqs=[],
        brief={"intent": "transactional"})
    assert not txn2["words"]["pass"], txn2["words"]


def test_render_prompt_states_intent_floor_and_target(monkeypatch):
    from lib.generation import render_prompt

    monkeypatch.delenv("GEN_MIN_WORDS", raising=False)
    txn = render_prompt({"keyword": "kw", "intent": "transactional"})
    assert "at least 400 words" in txn
    assert "400-700" in txn
    info = render_prompt({"keyword": "kw", "intent": ""})
    assert "at least 900 words" in info
    assert "1500-2500" in info


def test_brief_agent_prompt_has_fanout_and_announcement_guidance():
    from blog_agent.blog_agents import brief_agent

    instr = brief_agent.instructions
    for marker in ("## Fan-out Queries", "5-10 observed queries",
                   "H2/FAQ seed", "Do NOT invent search-volume",
                   'get_brief_template_tool("announcement")',
                   'get_brief_template_tool("press-release")',
                   "[VERIFY]", "NEVER invent a quote"):
        assert marker in instr, f"brief agent instructions missing: {marker}"


def test_get_brief_template_tool_serves_new_intents():
    from tools.ledger_tool import get_brief_template

    for intent in ("announcement", "press-release", "comparison"):
        out = get_brief_template(intent)
        assert out["status"] == "ok"
        assert out["template"]["word_floor"] > 0
        assert out["template_text"]
