"""§5.15 tactics tools — thin, agent-facing wrappers over `lib/tactics.py`.

Pure: no LLM, no network. Exposes the skill-pack citation plus the three brief
builders the Brief Agent needs — dedicated PAA pages (§3), comparison pages
(§21), and hub-and-spoke cluster planning (§22).
"""
from __future__ import annotations

import json
import os
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


def _paa_enabled() -> bool:
    return (os.environ.get("PAA_ATOMIZATION") or "").strip().lower() in ("1", "true", "yes", "on")


def _paa_pages_this_month(site_slug: str = "") -> int:
    """How many PAA page specs this site has produced in the last 30 days (audit rows). 0 if unreadable."""
    try:
        from datetime import datetime, timedelta, timezone

        from sqlalchemy import func, select

        from lib.db import AuditLog, get_session, init_db
        from lib.store import get_or_create_site

        init_db()
        s = get_session()
        try:
            site = get_or_create_site(s, site_slug)
            since = datetime.now(timezone.utc) - timedelta(days=30)
            return int(s.scalar(select(func.count()).select_from(AuditLog).where(
                AuditLog.site_id == site.id, AuditLog.action == "paa.page_spec",
                AuditLog.created_at >= since)) or 0)
        finally:
            s.close()
    except Exception:  # noqa: BLE001 - a counter must not break the tool
        return 0


def _record_paa_page(question: str, keyword: str, site_slug: str = "") -> None:
    try:
        from lib.db import AuditLog, get_session, init_db
        from lib.store import get_or_create_site

        init_db()
        s = get_session()
        try:
            site = get_or_create_site(s, site_slug)
            s.add(AuditLog(site_id=site.id, action="paa.page_spec",
                           payload={"question": question[:200], "keyword": keyword[:200]}))
            s.commit()
        finally:
            s.close()
    except Exception:  # noqa: BLE001
        pass


def build_paa_page(question: str, keyword: str, link_to: str = "", unique_data: str = "",
                   site_slug: str = "") -> Dict[str, Any]:
    """Build the spec for a dedicated page answering one PAA question (§3) - OPT-IN, with limits.

    One thin page per People-Also-Ask question is exactly the pattern Google's scaled-content-abuse policy
    targets, so this is OFF unless the operator sets PAA_ATOMIZATION=on, each page must name the original
    data / experience that makes it more than a rewording (`unique_data`), and a site gets at most
    PAA_MAX_PAGES (default 5) per 30 days (SEO-06).

    Args:
        question: The People-Also-Ask question this page answers.
        keyword: The parent keyword / cluster this question belongs to.
        link_to: URL/path of the originating article the page links up to.
        unique_data: What this page contains that the parent article and the SERP do not (own numbers, a test,
            a screenshot, first-hand experience). Required.

    Returns:
        {"status": "ok", "spec": {...}} or {"status": "error"|"disabled", "message": ...}.
    """
    if not (question or "").strip():
        return {"status": "error", "message": "question is required"}
    if not _paa_enabled():
        return {"status": "disabled",
                "message": ("PAA atomization is off. One page per question risks being treated as scaled, thin "
                            "content; answer the question inside the parent article's FAQ instead, or set "
                            "PAA_ATOMIZATION=on for a site with real unique data per question.")}
    if len((unique_data or "").strip()) < 40:
        return {"status": "error",
                "message": "unique_data is required (>= 40 chars): say what original data or first-hand "
                           "experience this page adds beyond the parent article"}
    try:
        cap = max(0, int(os.environ.get("PAA_MAX_PAGES") or 5))
    except ValueError:
        cap = 5
    if _paa_pages_this_month(site_slug) >= cap:
        return {"status": "error", "message": f"PAA page limit reached ({cap} per 30 days for this site)"}
    spec = build_paa_page_spec(question, keyword, link_to)
    spec["unique_data"] = unique_data.strip()
    _record_paa_page(question, keyword, site_slug)
    return {"status": "ok", "spec": spec}


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
