"""§5.16 keyword-ledger tools for the Brief Agent.

The brief stage may ONLY pull from ledger rows in `approved`/`queued` status —
no keyword row, no brief. Pure DB helpers around `lib/ledger` (no LLM, no
HTTP): the agent decides, the ledger gates.

Transitional bridge: the legacy pipeline keeps research in Google Sheets.
`register_brief_task_tool` lets the agent lift an unprocessed research row
into the ledger as `queued` (once), so the next brief is ledger-driven while
the Sheets→Postgres cutover (dual-write, then retire Sheets) completes.
"""
from __future__ import annotations

from typing import Any, Dict

from agents import function_tool
from sqlalchemy import select

from lib.brief_templates import template_for, template_text
from lib.db import KeywordLedger, Site, get_session, init_db
from lib.ledger import check_cannibalization as _check_cannibalization
from lib.ledger import next_keyword, set_status, upsert_keyword


def _resolve_site_id(session, site_slug: str) -> tuple[int | None, str]:
    if site_slug:
        site = session.execute(
            select(Site).where(Site.slug == site_slug)
        ).scalar_one_or_none()
        if site is None:
            return None, f"site '{site_slug}' not found"
        return site.id, ""
    site = session.execute(select(Site).order_by(Site.id.asc())).scalars().first()
    if site is None:
        return None, "no sites configured"
    return site.id, ""


def _row_payload(row: KeywordLedger) -> Dict[str, Any]:
    return {
        "status": "ok",
        "ledger_id": row.id,
        "keyword": row.keyword,
        "intent": row.intent or "informational",
        "volume": row.volume or 0,
        "difficulty": row.difficulty or 0.0,
        "priority_score": row.priority_score or 0.0,
        "cluster_id": row.cluster_id or "",
        "status_label": row.status,
        "research_snapshot": row.research_snapshot or {},
        "template": template_for(row.intent),
        "template_text": template_text(row.intent),
    }


def get_next_brief_task(site_slug: str = "") -> Dict[str, Any]:
    """Pull the next briefable keyword from the keyword ledger (§5.16).

    Briefs may ONLY be written for rows in `approved` or `queued` status —
    this is the gate. Returns the highest-priority briefable row including
    its search intent, a deterministic intent template for the brief
    structure, and the research snapshot captured at triage time.

    Args:
        site_slug: Optional site slug; defaults to the first configured site.

    Returns:
        {"status": "ok", "ledger_id", "keyword", "intent", "volume",
         "difficulty", "priority_score", "cluster_id", "research_snapshot",
         "template", "template_text"} on success, or
        {"status": "error", "message": "..."} when nothing is briefable
        (ledger empty / site missing). The message tells you to register a
        research row via register_brief_task_tool or wait for triage.
    """
    init_db()
    s = get_session()
    try:
        site_id, err = _resolve_site_id(s, site_slug)
        if site_id is None:
            return {"status": "error", "message": err}
        row = next_keyword(s, site_id)
        if row is None:
            return {
                "status": "error",
                "message": ("No approved/queued keywords in the ledger for "
                            f"site '{site_slug or 'default'}'. Either triage "
                            "new keywords or bridge a research_data row with "
                            "register_brief_task_tool."),
            }
        return _row_payload(row)
    finally:
        s.close()


def register_brief_task(keyword: str, intent: str = "informational",
                             site_slug: str = "") -> Dict[str, Any]:
    """Bridge a legacy research row into the keyword ledger as `queued` (§5.16).

    Transitional: use ONLY when get_next_brief_task_tool returns an error but
    an unprocessed research_data row exists. Creates the ledger row (or fills
    missing data) and moves it to `queued` so it becomes briefable. Existing
    rows are never downgraded — an `approved` row stays `approved`.

    Args:
        keyword: The keyword/topic string (exact research row keyword).
        intent: Search intent (informational/commercial/transactional/local/
            navigational). Defaults to "informational".
        site_slug: Optional site slug; defaults to the first configured site.

    Returns:
        {"status": "ok", "ledger_id", "keyword", "status_label"} or
        {"status": "error", "message": "..."}.
    """
    keyword = (keyword or "").strip()
    if not keyword:
        return {"status": "error", "message": "keyword is required"}
    init_db()
    s = get_session()
    try:
        site_id, err = _resolve_site_id(s, site_slug)
        if site_id is None:
            if err == "no sites configured":
                site = Site(slug=site_slug or "default",
                            name=(site_slug or "default").title())
                s.add(site)
                s.commit()
                s.refresh(site)
                site_id = site.id
            else:
                return {"status": "error", "message": err}
        row = upsert_keyword(s, site_id, keyword, intent=intent or "informational")
        if row.status == "researched":
            row = set_status(s, row.id, "queued")
        return {"status": "ok", "ledger_id": row.id, "keyword": row.keyword,
                "status_label": row.status}
    finally:
        s.close()


def get_brief_template(intent: str = "informational") -> Dict[str, Any]:
    """Deterministic brief template for a search intent (§5.16 intent templates).

    The brief's sections, H2 pattern, CTA posture and SERP-gap rule MUST
    follow this template — never invent your own structure. Unknown intents
    fall back to the informational template.

    Args:
        intent: One of informational, commercial, transactional, local,
            navigational.

    Returns:
        {"status": "ok", "template": {...}, "template_text": "..."}.
    """
    return {"status": "ok", "template": template_for(intent),
            "template_text": template_text(intent)}


def mark_brief_saved(keyword: str, site_slug: str = "") -> Dict[str, Any]:
    """Mark a ledger keyword as `briefed` AFTER the brief was saved (§5.16).

    Call this only once the brief exists in `content_briefs` (agent save or
    run_stage persistence both count). Advances the lifecycle so the keyword
    leaves the briefable queue and enters drafting.

    Args:
        keyword: Exact ledger keyword.
        site_slug: Optional site slug; defaults to the first configured site.

    Returns:
        {"status": "ok", "ledger_id", "keyword", "status_label": "briefed"}
        (plus "already": true when the row was already past briefing) or
        {"status": "error", "message": "..."} when the keyword has no ledger
        row or is in a status that must not be advanced.
    """
    keyword = (keyword or "").strip()
    if not keyword:
        return {"status": "error", "message": "keyword is required"}
    init_db()
    s = get_session()
    try:
        site_id, err = _resolve_site_id(s, site_slug)
        if site_id is None:
            return {"status": "error", "message": err}
        row = s.execute(
            select(KeywordLedger).where(KeywordLedger.site_id == site_id,
                                        KeywordLedger.keyword == keyword)
        ).scalar_one_or_none()
        if row is None:
            return {"status": "error",
                    "message": f"'{keyword}' has no ledger row — register it first"}
        if row.status in ("briefed", "drafted", "published"):
            return {"status": "ok", "ledger_id": row.id, "keyword": row.keyword,
                    "status_label": row.status, "already": True}
        if row.status not in ("approved", "queued", "researched"):
            return {"status": "error",
                    "message": f"cannot mark briefed from status '{row.status}'"}
        row = set_status(s, row.id, "briefed")
        return {"status": "ok", "ledger_id": row.id, "keyword": row.keyword,
                "status_label": row.status}
    finally:
        s.close()


# agents-SDK wrappers (the Brief Agent consumes these; tests call the plain
# functions above directly).
get_next_brief_task_tool = function_tool(get_next_brief_task, name_override="get_next_brief_task_tool")
register_brief_task_tool = function_tool(register_brief_task, name_override="register_brief_task_tool")
get_brief_template_tool = function_tool(get_brief_template, name_override="get_brief_template_tool")
mark_brief_saved_tool = function_tool(mark_brief_saved, name_override="mark_brief_saved_tool")


def check_cannibalization(keyword: str, site_slug: str = "") -> Dict[str, Any]:
    """§5.3/§5.16 intent-overlap triage — run BEFORE queueing/approving a keyword.

    Compares the candidate against every non-retired ledger row. A high
    intent-overlap means two pages would compete for the same query, so the
    keyword must be merged into the existing row or the angle differentiated —
    never two competing rows.

    Args:
        keyword: The candidate keyword.
        site_slug: Optional site slug; defaults to the first configured site.

    Returns:
        {"status": "ok", "keyword", "overlap", "with_keyword", "overlap_ratio",
         "decision": "write"|"differentiate"|"merge"} or {"status": "error", ...}.
        decision: write (no overlap), differentiate (0.6-0.8 — keep but angle
        it apart), merge (>=0.8 — near-duplicate, collapse into the existing row).
    """
    keyword = (keyword or "").strip()
    if not keyword:
        return {"status": "error", "message": "keyword is required"}
    init_db()
    s = get_session()
    try:
        site_id, err = _resolve_site_id(s, site_slug)
        if site_id is None:
            return {"status": "error", "message": err}
        res = _check_cannibalization(s, site_id, keyword)
        if not res["overlap"]:
            decision = "write"
        else:
            decision = "merge" if res["overlap_ratio"] >= 0.8 else "differentiate"
        return {"status": "ok", "keyword": keyword, **res, "decision": decision}
    finally:
        s.close()


check_cannibalization_tool = function_tool(
    check_cannibalization, name_override="check_cannibalization_tool")
