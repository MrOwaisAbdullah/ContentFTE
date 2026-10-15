"""Keyword targets from the operator's sheet, end to end.

Covers: the sheet's four columns (resolved by header name, never position),
parsing/dedup/cap of the keyword cell, carrying them through the ledger,
the hard gate on both gate surfaces, and the Sanity field that stores them.
"""
from __future__ import annotations

import os


def _read(*parts: str) -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, *parts), encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# Sheet side
# ---------------------------------------------------------------------------

def test_keyword_sheet_column_map_is_header_resolved():
    """Status is no longer column 2: the sheet is Topic/YT Transcript,
    Primary Keyword, Secondary Keywords, Status -- so a hardcoded
    update_cell(i, 2) would silently overwrite the primary keyword."""
    src = _read("tools", "sheet_tool.py")
    assert "KEYWORD_SHEET_COLUMNS" in src
    assert "def _column_index" in src
    assert "update_cell(i, 2" not in src
    assert "update_cell(row_index, 2" not in src
    # the legacy singular "Keyword" column survives only as a fallback
    assert '"Keyword"' in src


def test_get_keyword_tool_returns_keyword_targets():
    from tools.sheet_tool import _column_index

    header = ["Topic/YT Transcript", "Primary Keyword",
              "Secondary Keywords", "Status"]
    col = _column_index(header)
    assert col["subject"] == "Topic/YT Transcript" and col["subject_pos"] == 1
    assert col["primary"] == "Primary Keyword" and col["primary_pos"] == 2
    assert col["secondary"] == "Secondary Keywords"
    assert col["status"] == "Status" and col["status_pos"] == 4

    # a legacy sheet still resolves: subject falls back to the old name
    legacy = _column_index(["Keyword", "Status"])
    assert legacy["subject"] == "Keyword" and legacy["status_pos"] == 2


def test_keyword_claim_carries_the_targets():
    from tools.sheet_tool import clear_keyword_claim, keyword_claim_keywords

    clear_keyword_claim()
    assert keyword_claim_keywords() == {"subject": "", "primary": "",
                                        "secondary": ""}


def test_research_row_writes_the_keyword_columns():
    src = _read("blog_agent", "research_agent.py")
    assert "        primary_keyword," in src
    assert "        secondary_keywords," in src


# ---------------------------------------------------------------------------
# Storage side
# ---------------------------------------------------------------------------

def test_store_maps_the_new_columns():
    from lib.store import map_research_row

    row = ["coffee makers", "1000", "20", "commercial",
           "A summary.", "https://a.example", "Source A", "No",
           "best coffee maker", "compact coffee maker; small coffee maker"]
    headers = ["Keyword/Topic", "Search Volume", "Difficulty", "User Intent",
               "Content Summary", "Source URLs", "Source Titles", "Generated",
               "Primary Keyword", "Secondary Keywords"]
    mapped = map_research_row(row, headers)
    assert mapped["primary_keyword"] == "best coffee maker"
    assert mapped["secondary_keywords"] == "compact coffee maker; small coffee maker"
    # primary wins as the ledger keyword; the topic stays as the subject
    assert mapped["keyword"] == "best coffee maker"
    assert mapped["subject"] == "coffee makers"


def test_map_research_row_falls_back_to_the_topic():
    """A legacy row with no keyword columns must still map."""
    from lib.store import map_research_row

    mapped = map_research_row(["coffee makers", "No"])
    assert mapped["keyword"] == "coffee makers"
    assert mapped["primary_keyword"] == "" and mapped["secondary_keywords"] == ""


def test_mirrors_carry_secondaries_into_the_snapshot():
    src = _read("lib", "store.py")
    assert '"secondary_keywords": secondary_keywords,' in src
    assert "secondary_keywords: str = \"\"," in src


def test_ledger_payload_exposes_secondaries():
    src = _read("tools", "ledger_tool.py")
    assert '"secondary_keywords": str(' in src


# ---------------------------------------------------------------------------
# Prompt side
# ---------------------------------------------------------------------------

def test_brief_template_requires_no_secondary_section_without_targets():
    from lib.brief_templates import secondary_keywords_block

    assert secondary_keywords_block("") == ""
    assert secondary_keywords_block("   ") == ""
    block = secondary_keywords_block("compact coffee maker")
    assert "compact coffee maker" in block
    assert "keyword gate rejects" in block
    # over the cap: dropped with the cap stated, never gated on
    many = "; ".join(f"keyword {i}" for i in range(6))
    block = secondary_keywords_block(many)
    assert block.count("- keyword") == 3


def test_build_brief_payload_carries_only_supplied_keywords():
    from lib.generation import build_brief_payload

    with_targets = build_brief_payload(
        keyword="coffee maker", intent="informational",
        brief_meta={"secondary_keywords": "compact coffee maker"})
    assert "compact coffee maker" in with_targets["secondary_keywords"]

    without = build_brief_payload(keyword="coffee maker", intent="informational")
    assert without["secondary_keywords"] == ""
    assert "Secondary Keywords" not in without["brief_markdown"]


def test_brief_payload_reads_keywords_from_research_snapshot():
    """The ledger stores the targets inside research_snapshot, so the
    snapshot path must surface them too."""
    from lib.generation import build_brief_payload

    payload = build_brief_payload(
        keyword="coffee maker", intent="informational",
        research_snapshot=json_dumps(
            {"summary": "s", "secondary_keywords": "thermal carafe"}))
    assert "thermal carafe" in payload["secondary_keywords"]


def json_dumps(payload: dict) -> str:
    import json
    return json.dumps(payload)


def test_generator_prompt_states_slots_not_just_counts():
    src = _read("blog_agent", "blog_agents.py")
    assert "Keyword placement — each keyword has a slot, not just a count." in src
    assert "ONE H2 or H3 heading of its own" in src
    assert "Never put a secondary keyword in the H1/title" in src
    # the brief agent must never write an invented secondary list
    assert "do not invent them here" in src


# ---------------------------------------------------------------------------
# Gate side
# ---------------------------------------------------------------------------

def test_run_stage_gates_before_persisting():
    src = _read("scripts", "run_stage.py")
    assert "def _enforce_keyword_gate" in src
    assert "_enforce_keyword_gate(parsed, source_brief)" in src
    # it runs before the persist call, not after
    assert src.index("_enforce_keyword_gate(parsed, source_brief)") < src.index(
        "persisted_row = _ensure_content_persisted(parsed, source_brief)")


def test_sdk_gate_gates_secondaries_not_the_topic():
    """The primary keyword is the ledger topic, already enforced by the
    prompts (H1/TL;DR/intro) -- gating it rejects a draft that legitimately
    uses it once. Only the operator's secondary targets are hard-gated."""
    from sdk import service

    content = (
        "# Best CRM\n\n"
        "> **TL;DR** - The compact crm is the answer here for now and later.\n\n"
        "## Why it matters\n\nThe crm you pick matters a lot.\n"
    )
    checks = service._content_checks(
        content=content, title="Best CRM", summary="A" * 60,
        faqs=[{"question": "Q", "answer": "A"}] * 4,
        brief={"keyword": "crm", "secondary_keywords": "thermal carafe"})
    assert "keyword_usage" in checks
    assert checks["keyword_usage"]["pass"] is False
    assert checks["keyword_usage"]["missing"] == ["thermal carafe"]
    joined = " ".join(checks["keyword_usage"]["guidance"])
    assert "thermal carafe" in joined and "needs 2" in joined


def test_sdk_gate_absent_when_no_secondaries_supplied():
    from sdk import service

    checks = service._content_checks(
        content="Body.", title="T", summary="S" * 60, faqs=[],
        brief={"keyword": "coffee maker", "secondary_keywords": ""})
    assert "keyword_usage" not in checks


def test_run_stage_gate_helper_fails_open_without_targets():
    import scripts.run_stage as rs

    parsed = {"Generated Content": "anything", "Title": "t"}
    rs._enforce_keyword_gate(
        parsed, {"data": {"Keyword/Topic": "coffee maker"}})


def test_run_stage_gate_helper_raises_with_report():
    import pytest
    import scripts.run_stage as rs

    parsed = {"Generated Content": "A coffee maker paragraph only.",
              "Title": "Best Coffee Maker"}
    with pytest.raises(RuntimeError) as exc:
        rs._enforce_keyword_gate(
            parsed, {"data": {"Keyword/Topic": "coffee maker",
                              "Secondary Keywords": "thermal carafe"}})
    assert "thermal carafe" in str(exc.value)
    assert "keyword gate failed" in str(exc.value)


def test_run_stage_persist_appends_brief_keywords(monkeypatch):
    """Regression (2026-10-15 content run): _ensure_content_persisted
    referenced `source_brief` without it ever being in scope there -- it
    only exists as a local in run_content -- so the deterministic save that
    runs when the agent generated a full post but didn't append the row
    itself died with a NameError AFTER the whole (paid) generation. Drive
    the append path against a stubbed sheet and assert the row carries the
    brief's Secondary Keywords."""
    import scripts.run_stage as rs

    appended = {}

    def fake_manage_sheet_data(**kwargs):
        action = kwargs.get("action")
        if action == "get_all_records":
            return {"status": "success", "data": []}
        if action == "get_range":  # header row: every column already exists
            return {"status": "success", "data": [[
                "Title", "Generated Content", "FAQs", "Quality Score",
                "Summary", "Approve/Disapprove", "Published",
                "Repurpose Bundle", "Video Script Seed",
                "Secondary Keywords", "Created At",
            ]]}
        if action == "find_row_by_key":
            return {"status": "success", "found": False}
        if action == "append_row":
            appended["row_values"] = kwargs.get("row_values")
            return {"status": "success", "message": "Row appended to generated_posts."}
        raise AssertionError(f"unexpected sheet call: {kwargs}")

    monkeypatch.setattr(rs, "manage_sheet_data", fake_manage_sheet_data)
    content = {
        "Title": "Claude Agent SDK vs OpenAI Agents SDK Error Handling",
        "Generated Content": "A body without links.",
        "Quality Score": "92",
        "Summary": "A summary.",
    }
    row = rs._ensure_content_persisted(
        content,
        {"data": {"Keyword/Topic": "coffee maker",
                  "Secondary Keywords": "thermal carafe; coffee grinder"}},
    )
    assert row["Title"] == content["Title"]
    assert row["Secondary Keywords"] == "thermal carafe; coffee grinder"
    assert appended["row_values"][-1] == "thermal carafe; coffee grinder"


# ---------------------------------------------------------------------------
# Sanity side
# ---------------------------------------------------------------------------

def test_sanity_schema_and_adapter_store_secondaries():
    schema = _read("sdk", "sanity", "schemaTypes", "postType.ts")
    assert 'name: "secondaryKeywords"' in schema
    adapter = _read("lib", "sanity_adapter.py")
    assert 'document["secondaryKeywords"] = list(secondary_keywords)' in adapter
    tool = _read("tools", "tools.py")
    assert "secondary_keywords or []" in tool
    agent = _read("blog_agent", "posting_agent.py")
    assert "secondary_keywords: the extracted SECONDARY_KEYWORDS" in agent


def test_site_schema_stores_secondaries():
    site = os.path.join("D:", "GIAIC", "Real World Projects", "Owais-Abdullah",
                        "sanity", "schemaTypes", "postType.ts")
    if not os.path.isfile(site):
        import pytest
        pytest.skip("Owais-Abdullah repo not present on this machine")
    with open(site, encoding="utf-8") as fh:
        src = fh.read()
    assert 'name: "secondaryKeywords"' in src
