"""§5.3 discrete fact-check gate — draft → fact-check → revise → eval.

Wraps lib.factcheck (pure deterministic: claim extraction + source matching,
no LLM) as an agents SDK tool so the Content Generator must run it BEFORE
`get_evaluation_feedback`. The frontier critic never spends tokens on
unverified claims.
"""
from __future__ import annotations

import json
from typing import Any, Dict

from agents import function_tool

from lib.factcheck import gate_factcheck


def run_factcheck_gate(
    draft_markdown: str,
    source_excerpts_json: str = "[]",
    check_links: bool = False,
) -> Dict[str, Any]:
    """Run the mandatory fact-check gate on a draft BEFORE evaluation.

    Extracts every numeric/date/price claim from the draft and matches each
    against the research excerpts you pass in. This gate is deterministic
    (no LLM) and MUST run before `get_evaluation_feedback` — order is
    draft → fact-check → revise → eval.

    Args:
        draft_markdown: The full draft body to verify (Markdown, no H1).
        source_excerpts_json: JSON array of source excerpt strings from the
            research step, e.g. '["Nespresso brews in 30 seconds per review"]'.
        check_links: Also HEAD-check every external link in the draft
            (network call; keep False unless links changed this run).

    Returns:
        JSON dict:
        {
          "pass": bool,               # false → REVISE, do not call eval yet
          "claim_count": int,
          "unverified_count": int,
          "unverified": [{"claim": str, "context": str, "fix_hint": str}],
          "guidance": str             # what the revision must do
        }
        On malformed input returns {"pass": false, "error": "..."}.
    """
    try:
        excerpts = json.loads(source_excerpts_json or "[]")
        if not isinstance(excerpts, list):
            raise ValueError("source_excerpts_json must be a JSON array")
    except (json.JSONDecodeError, ValueError) as e:
        return {"pass": False, "error": f"invalid source_excerpts_json: {e}"}

    result = gate_factcheck(draft_markdown or "", excerpts)
    unverified = []
    for item in result.get("unverified", []):
        unverified.append({
            "claim": item.get("claim", ""),
            "context": item.get("context", ""),
            "fix_hint": "find a source for this exact number/date in Tavily, "
                        "attribute it inline (e.g. 'According to X...'), or "
                        "remove/soften the claim",
        })
    if check_links:
        from lib.factcheck import extract_claims, verify_claims

        verified = verify_claims(extract_claims(draft_markdown or ""),
                                 excerpts, check_links=True,
                                 markdown=draft_markdown or "")
        result["link_report"] = verified.get("link_report")

    return {
        "pass": bool(result["pass"]),
        "claim_count": result["claim_count"],
        "unverified_count": result["unverified_count"],
        "unverified": unverified,
        "guidance": (
            "All claims grounded — proceed to evaluation."
            if result["pass"]
            else f"{result['unverified_count']} unsourced claim(s) found. "
                 "Revise FIRST (source, attribute, or remove each), re-run this "
                 "gate until pass=true, THEN call get_evaluation_feedback."
        ),
        "link_report": result.get("link_report"),
    }


# Agent-facing tool (LLM calls `factcheck_gate_tool`; plain code should call
# `run_factcheck_gate` directly — no agent context needed).
factcheck_gate_tool = function_tool(run_factcheck_gate)
