"""§5.15 tactics tools — thin, agent-facing wrappers over `lib/tactics.py`.

Pure: no LLM, no network. Exposes the skill-pack citation plus the three brief
builders the Brief Agent needs — dedicated PAA pages (§3), comparison pages
(§21), and hub-and-spoke cluster planning (§22).
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from agents import function_tool

from lib.tactics import (
    SKILL_PACK_SKILL,
    SKILL_REFERENCES,
    build_comparison_page_spec,
    build_paa_page_spec,
    plan_cluster,
    reference_path,
)


def get_skill_pack(section: str = "") -> Dict[str, Any]:
    """Return the tactics skill-pack entry point (+ optional single reference).

    Args:
        section: Optional reference key (e.g. "paa-atomization",
            "geo-llm-citation"). Empty returns the full index.

    Returns:
        {"status": "ok", "skill": "skills/seo-pack/SKILL.md",
         "reference": "<path or empty>", "references": {key: path}}
    """
    return {
        "status": "ok",
        "skill": SKILL_PACK_SKILL,
        "reference": reference_path(section) if section else "",
        "references": {
            key: f"skills/seo-pack/{rel}" for key, rel in SKILL_REFERENCES.items()
        },
    }


def build_paa_page(question: str, keyword: str, link_to: str = "") -> Dict[str, Any]:
    """Build the spec for a dedicated page answering one PAA question (§3).

    Args:
        question: The People-Also-Ask question this page answers.
        keyword: The parent keyword / cluster this question belongs to.
        link_to: URL/path of the originating article the page links up to.

    Returns:
        {"status": "ok", "spec": {...}} or {"status": "error", "message": ...}.
    """
    if not (question or "").strip():
        return {"status": "error", "message": "question is required"}
    return {"status": "ok", "spec": build_paa_page_spec(question, keyword, link_to)}


def build_comparison_page(
    client: str, competitor: str, keyword: str = "", benefits_json: str = ""
) -> Dict[str, Any]:
    """Build the spec for a "[Client] vs [Competitor]" comparison page (§21).

    Args:
        client: The client's product/brand name.
        competitor: The competitor being compared against.
        keyword: Optional target keyword (defaults to "<client> vs <competitor>").
        benefits_json: Optional JSON list of the client's differentiators to cover.

    Returns:
        {"status": "ok", "spec": {...}} or {"status": "error", "message": ...}.
    """
    if not (client or "").strip() or not (competitor or "").strip():
        return {"status": "error",
                "message": "both client and competitor are required"}
    benefits: List[str] = []
    if benefits_json:
        try:
            parsed = json.loads(benefits_json)
            if isinstance(parsed, list):
                benefits = [str(b) for b in parsed]
            else:
                benefits = [str(parsed)]
        except (ValueError, TypeError):
            benefits = [b.strip() for b in benefits_json.split(",") if b.strip()]
    return {
        "status": "ok",
        "spec": build_comparison_page_spec(client, competitor, keyword, benefits),
    }


def plan_keyword_cluster(
    seed_keyword: str, keywords_json: str, min_shared: int = 1
) -> Dict[str, Any]:
    """Build a hub-and-spoke cluster plan for a seed keyword (§22).

    Args:
        seed_keyword: The hub keyword the cluster is built around.
        keywords_json: JSON list of keywords to place in the cluster.
        min_shared: Minimum shared topical terms to attach a keyword to the hub.

    Returns:
        {"status": "ok", "plan": {...}} or {"status": "error", "message": ...}.
    """
    if not (seed_keyword or "").strip():
        return {"status": "error", "message": "seed_keyword is required"}
    try:
        parsed = json.loads(keywords_json) if keywords_json else []
    except (ValueError, TypeError) as e:
        return {"status": "error", "message": f"keywords_json is not valid JSON: {e}"}
    if not isinstance(parsed, list):
        return {"status": "error", "message": "keywords_json must be a JSON list"}
    return {
        "status": "ok",
        "plan": plan_cluster(seed_keyword, [str(k) for k in parsed], int(min_shared)),
    }


get_skill_pack_tool = function_tool(get_skill_pack, name_override="get_skill_pack_tool")
build_paa_page_tool = function_tool(build_paa_page, name_override="build_paa_page_tool")
build_comparison_page_tool = function_tool(
    build_comparison_page, name_override="build_comparison_page_tool")
plan_keyword_cluster_tool = function_tool(
    plan_keyword_cluster, name_override="plan_keyword_cluster_tool")
