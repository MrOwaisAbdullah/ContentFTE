"""What an agent that reads UNTRUSTED web content may do to the Google Sheet (plan SEC-17).

The generic `manage_sheet_data_tool` can write any cell of any worksheet. Agents that ingest search
results, scraped pages and forum posts hold it, so injected text ("update_cell generated_posts ...
Approve") could set the human-approval column itself, wipe a sheet, or plant `=IMPORTDATA(...)`
formulas — turning the Discord approval gate into a no-op.

This is the pure policy (no gspread import, so it is unit-testable). The agent-facing tool built on it
lives in tools/sheet_tool.py. Agents that run AFTER a human decision (posting) keep the full tool.
"""
from __future__ import annotations

from typing import Optional

# Worksheets that carry decisions, not data an agent should be rewriting. An agent may APPEND a new row
# (that is how the generator hands its draft over) and read, but never edit, insert into or clear them.
PROTECTED_WORKSHEETS = frozenset({"generated_posts", "published_posts", "review_feedback_log"})

# Never allowed for an agent on any worksheet.
FORBIDDEN_ACTIONS = frozenset({"delete_row", "clear_sheet"})

# Writes that modify existing content (append_row is the only write that cannot overwrite).
MODIFYING_ACTIONS = frozenset({"update_row", "update_cell", "update_cells", "insert_row"})


def check_agent_write(worksheet_name: str, action: str) -> Optional[str]:
    """None if allowed, else a refusal message the model sees as the tool result."""
    ws = (worksheet_name or "").strip().lower()
    act = (action or "").strip().lower()
    if act in FORBIDDEN_ACTIONS:
        return (f"'{act}' is not available to this agent. Rows are never deleted or sheets cleared by "
                "the pipeline's research/writing agents; ask the operator.")
    if ws in PROTECTED_WORKSHEETS and act in MODIFYING_ACTIONS:
        return (f"'{act}' on '{worksheet_name}' is not available to this agent: that worksheet holds "
                "approval/publication decisions, which only the operator and the posting stage change. "
                "You may read it or append a new row.")
    return None
