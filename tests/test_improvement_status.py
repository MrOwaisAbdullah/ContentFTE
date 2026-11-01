"""The status board is the single place progress is tracked; this keeps it honest."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _board():
    spec = importlib.util.spec_from_file_location("improvement_status", ROOT / "scripts" / "improvement_status.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_every_finding_in_the_plan_has_a_status_and_nothing_extra():
    b = _board()
    errs = b.problems(b.plan_findings(), b.load_status())
    assert errs == [], "\n".join(errs)


def test_the_rendered_board_is_up_to_date():
    b = _board()
    rendered = b.render(b.plan_findings(), b.load_status())
    on_disk = (ROOT / "docs" / "improvement-status.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert on_disk == rendered, "docs/improvement-status.md is stale - run: python scripts/improvement_status.py"


def test_the_check_mode_agrees():
    assert _board().main(["--check"]) == 0


def test_partial_decision_and_owner_items_say_what_is_left():
    b = _board()
    for fid, e in b.load_status()["items"].items():
        if e["status"] in ("partial", "decision", "owner"):
            assert e.get("note"), f"{fid} is '{e['status']}' but has no note"


def test_done_items_name_the_branch_that_contains_them():
    b = _board()
    data = b.load_status()
    for fid, e in data["items"].items():
        if e["status"] == "done":
            assert e.get("branch") in data["branches"], f"{fid} is done but names no valid branch"


def test_unknown_statuses_are_rejected():
    b = _board()
    findings = {"SEC-01": {"severity": "High", "title": "t"}}
    bad = {"items": {"SEC-01": {"status": "finished"}}, "branches": {}}
    assert any("invalid status" in e for e in b.problems(findings, bad))
    missing = {"items": {}, "branches": {}}
    assert any("missing from improvement-status.json" in e for e in b.problems(findings, missing))
