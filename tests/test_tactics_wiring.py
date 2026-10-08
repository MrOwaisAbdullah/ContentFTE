"""§5.15 tactics wiring: skill-pack existence + citation, the PAA/comparison
brief builders, cluster planning, and the agent references that point at them.

The skill pack is a tracked artifact (skills/seo-pack/); `lib/tactics.py` and
`tools/tactics_tool.py` are pure (no LLM/network). Mirrored to
~/.claude/skills/seo-pack/ for Claude Code sessions.
"""
import json
import os

import pytest

from lib import tactics
from tools import tactics_tool

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# Skill pack artifacts
# ---------------------------------------------------------------------------
def test_skill_pack_files_exist():
    skill = os.path.join(REPO_ROOT, tactics.SKILL_PACK_SKILL)
    assert os.path.isfile(skill), f"missing {skill}"
    assert len(tactics.SKILL_REFERENCES) == 13
    for key, rel in tactics.SKILL_REFERENCES.items():
        path = os.path.join(REPO_ROOT, tactics.SKILL_PACK_DIR, rel)
        assert os.path.isfile(path), f"missing reference for {key}: {path}"


def test_reference_path_known_and_unknown():
    p = tactics.reference_path("keyword-strategy")
    assert p.endswith("references/keyword-strategy.md")
    # unknown section never 404s mid-prompt -- falls back to SKILL.md
    assert tactics.reference_path("does-not-exist") == tactics.SKILL_PACK_SKILL


def test_skill_pack_block_cites_path_and_refs():
    block = tactics.skill_pack_block()
    assert tactics.SKILL_PACK_SKILL in block
    assert "references/keyword-strategy.md" in block
    assert "references/eval-gates.md" in block


# ---------------------------------------------------------------------------
# classify_keyword
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("kw,expected", [
    ("WordPress vs Squarespace", "comparison"),
    ("Notion versus Evernote", "comparison"),
    ("Airtable compared to Excel", "comparison"),
    ("best CRM for dental clinics", "listicle"),
    ("cheapest vpn", "listicle"),
    ("what is a knowledge graph", "article"),
])
def test_classify_keyword(kw, expected):
    assert tactics.classify_keyword(kw) == expected


# ---------------------------------------------------------------------------
# PAA + comparison builders
# ---------------------------------------------------------------------------
def test_build_paa_page_spec():
    spec = tactics.build_paa_page_spec(
        "How long does SEO take to work?", "seo timeline", link_to="/blog/seo-timeline/")
    assert spec["page_type"] == "paa"
    assert spec["h1"] == "How long does SEO take to work?"
    assert spec["target_words"] == 120
    assert "/faq/" in spec["url_path"]
    assert spec["faq_schema"] is True
    assert spec["internal_link_to"] == "/blog/seo-timeline/"
    assert spec["reference"].endswith("brief-research.md")


def test_build_comparison_page_spec():
    spec = tactics.build_comparison_page_spec(
        "ContentFTE", "Jasper", "contentfte vs jasper", benefits=["automation"])
    assert spec["h1"] == "ContentFTE vs Jasper"
    assert spec["client"] == "ContentFTE"
    assert spec["competitor"] == "Jasper"
    assert spec["neutral_tone"] is True
    assert spec["competitor_linked"] is True
    assert spec["factcheck_required"] is True
    assert spec["client_differentiators"] == ["automation"]
    assert len(spec["required_sections"]) >= 5
    assert any("competitor" in r.lower() for r in spec["rules"])
    assert spec["reference"].endswith("coverage-multiplication.md")


# ---------------------------------------------------------------------------
# Cluster planning
# ---------------------------------------------------------------------------
def test_plan_cluster_groups_and_reports_holes():
    plan = tactics.plan_cluster(
        "email marketing automation",
        ["email marketing tools", "marketing automation pricing", "sourdough recipes"],
    )
    assert plan["hub"] == "email marketing automation"
    assert plan["assigned_pct"] == 67  # 2 of 3 attach to the hub
    assert plan["holes"] == 1
    kws = {s["keyword"] for s in plan["spokes"]}
    assert "email marketing tools" in kws
    assert "sourdough recipes" not in kws
    assert plan["uncovered"] == ["sourdough recipes"]


def test_plan_cluster_empty_is_safe():
    plan = tactics.plan_cluster("seed keyword", [])
    assert plan["assigned_pct"] == 0
    assert plan["spokes"] == []


# ---------------------------------------------------------------------------
# tools/tactics_tool.py wrappers
# ---------------------------------------------------------------------------
def test_get_skill_pack_tool():
    out = tactics_tool.get_skill_pack()
    assert out["status"] == "ok"
    assert out["skill"] == tactics.SKILL_PACK_SKILL
    assert len(out["references"]) == 13
    # section-scoped call returns one reference
    out2 = tactics_tool.get_skill_pack("eval-gates")
    assert out2["reference"].endswith("references/eval-gates.md")


def test_build_paa_page_tool_requires_question():
    assert tactics_tool.build_paa_page("", "kw")["status"] == "error"
    ok = tactics_tool.build_paa_page("What is X?", "kw")
    assert ok["status"] == "ok"
    assert ok["spec"]["page_type"] == "paa"


def test_build_comparison_page_tool_requires_both():
    assert tactics_tool.build_comparison_page("A", "")["status"] == "error"
    assert tactics_tool.build_comparison_page("", "B")["status"] == "error"
    ok = tactics_tool.build_comparison_page("A", "B")
    assert ok["status"] == "ok"
    assert ok["spec"]["h1"] == "A vs B"


def test_plan_keyword_cluster_tool_json_handling():
    assert tactics_tool.plan_keyword_cluster("", "[]")["status"] == "error"
    assert tactics_tool.plan_keyword_cluster("kw", "not json")["status"] == "error"
    assert tactics_tool.plan_keyword_cluster("kw", '{"a":1}')["status"] == "error"
    ok = tactics_tool.plan_keyword_cluster(
        "email marketing", json.dumps(["email marketing tools"]))
    assert ok["status"] == "ok"
    assert ok["plan"]["hub"] == "email marketing"


# ---------------------------------------------------------------------------
# Agent wiring (prompts cite the skill pack; brief agent has the new tools)
# ---------------------------------------------------------------------------
def _tool_names(agent):
    return {
        getattr(t, "name", None) or getattr(t, "tool_name", None)
        for t in agent.tools
    }


def test_brief_agent_has_tactics_tools():
    from blog_agent.blog_agents import brief_agent

    names = _tool_names(brief_agent)
    for tool in ("get_skill_pack_tool", "build_paa_page_tool",
                 "build_comparison_page_tool", "plan_keyword_cluster_tool"):
        assert tool in names, tool


def test_brief_agent_instructions_cite_skill_pack_and_brief_types():
    from blog_agent.blog_agents import brief_agent

    txt = brief_agent.instructions
    assert "skills/seo-pack/SKILL.md" in txt
    assert "get_skill_pack_tool" in txt
    assert "PAA Atomization" in txt
    assert "Comparison Page Spec" in txt
    assert "Cluster Plan" in txt


def test_draft_and_eval_agents_cite_skill_pack():
    from blog_agent.blog_agents import content_generator_agent, content_evaluation_agent

    assert "skills/seo-pack/SKILL.md" in content_generator_agent.instructions
    assert "skills/seo-pack/SKILL.md" in content_evaluation_agent.instructions
