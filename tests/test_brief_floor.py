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


def test_tutorial_queries_get_a_higher_floor_but_compact_pages_do_not(monkeypatch):
    """SEO-26: 900 words is below what wins how-to queries."""
    from lib.brief_templates import word_floor_for
    monkeypatch.delenv("GEN_MIN_WORDS", raising=False)
    monkeypatch.delenv("TUTORIAL_WORD_FLOOR", raising=False)
    assert word_floor_for("informational", "how to build an agent with mcp") == 1500
    assert word_floor_for("commercial", "step-by-step crm setup") == 1500
    assert word_floor_for("informational", "what is an ai agent") == 900          # not a tutorial query
    assert word_floor_for("transactional", "how to buy x") == 400                  # compact pages stay compact
    monkeypatch.setenv("TUTORIAL_WORD_FLOOR", "1800")
    assert word_floor_for("informational", "tutorial: rag pipeline") == 1800
    monkeypatch.setenv("GEN_MIN_WORDS", "700")                                     # operator override still wins
    assert word_floor_for("informational", "how to build an agent") == 700


def test_faq_requirement_is_configurable_per_brief_and_per_instance(monkeypatch):
    """SEO-20: a FAQ block on every post is a template footprint."""
    from lib.brief_templates import faq_min_for
    monkeypatch.delenv("FAQ_MIN", raising=False)
    assert faq_min_for({}) == 3 and faq_min_for(None) == 3
    assert faq_min_for({"faq_required": False}) == 0
    assert faq_min_for({"faq_min": 5}) == 5 and faq_min_for({"faq_min": 99}) == 10
    monkeypatch.setenv("FAQ_MIN", "0")
    assert faq_min_for({}) == 0
    assert faq_min_for({"faq_min": 4}) == 4                      # the brief beats the instance default


def test_zero_faqs_passes_the_draft_check_only_when_faqs_are_optional(monkeypatch):
    from sdk import service
    monkeypatch.delenv("FAQ_MIN", raising=False)
    body = "# T\n\n> **TL;DR** x\n\n" + ("word " * 1000) + "\n\n## Sources\n- s\n"
    strict = service._content_checks(content=body, title="T", summary="s" * 40, faqs=[], brief={"keyword": "k"})
    assert strict["faqs"]["pass"] is False
    relaxed = service._content_checks(content=body, title="T", summary="s" * 40, faqs=[],
                                      brief={"keyword": "k", "faq_required": False})
    assert relaxed["faqs"]["pass"] is True and relaxed["faqs"]["need"] == 0


# ---- CON-05: the site's Content settings are READ by the engine -----------------------------------------------------
def test_site_content_settings_reach_the_brief_and_drive_the_floor_faqs_and_voice(monkeypatch):
    from lib.brief_templates import faq_min_for, word_floor_for_brief
    from sdk import service
    monkeypatch.delenv("GEN_MIN_WORDS", raising=False)
    monkeypatch.delenv("FAQ_MIN", raising=False)

    class Site:
        settings = {"content": {"min_words": 1200, "generate_faqs": False, "brand_voice_prompt": "Dry, precise, no hype."}}

    brief = service.apply_site_content_settings({"keyword": "best crm", "intent": "informational"}, Site())
    assert brief["min_words"] == 1200 and word_floor_for_brief(brief) == 1200
    assert faq_min_for(brief) == 0 and brief["brand_voice_prompt"] == "Dry, precise, no hype."
    # a per-article value on the brief wins over the site default
    assert service.apply_site_content_settings({"min_words": 500, "faq_required": True}, Site())["min_words"] == 500
    assert faq_min_for(service.apply_site_content_settings({"faq_required": True}, Site())) == 3
    # garbage / absent settings change nothing
    class Bad:
        settings = {"content": {"min_words": "lots", "generate_faqs": "maybe"}}
    assert service.apply_site_content_settings({"keyword": "k"}, Bad()) == {"keyword": "k"}
    assert service.apply_site_content_settings({"keyword": "k"}, None) == {"keyword": "k"}
    # nothing set: the intent/tutorial floor applies, and the operator's GEN_MIN_WORDS still outranks the site
    assert word_floor_for_brief({"intent": "informational", "keyword": "what is x"}) == 900
    monkeypatch.setenv("GEN_MIN_WORDS", "700")
    assert word_floor_for_brief(brief) == 700


def test_the_generation_prompt_carries_the_sites_voice_instructions(monkeypatch):
    monkeypatch.delenv("GEN_MIN_WORDS", raising=False)
    from lib.generation import render_prompt
    base = {"keyword": "best crm", "intent": "informational", "brief_payload": "x"}
    with_voice = render_prompt({**base, "brand_voice_prompt": "Dry, precise, no hype.", "min_words": 1234})
    assert "Dry, precise, no hype." in with_voice and "1234 words" in with_voice
    assert "Site voice instructions" not in render_prompt(base)
