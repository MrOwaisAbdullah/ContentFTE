"""Plan SEC-17: web-reading agents get a sheet tool that cannot self-approve, delete or run formulas."""
from __future__ import annotations

import importlib
import os

import pytest

from tools.sheet_guard import check_agent_write


@pytest.mark.parametrize("ws", ["generated_posts", "Generated_Posts", "published_posts", "review_feedback_log"])
@pytest.mark.parametrize("action", ["update_row", "update_cell", "update_cells", "insert_row"])
def test_agents_cannot_modify_decision_worksheets(ws, action):
    msg = check_agent_write(ws, action)
    assert msg and "not available" in msg


@pytest.mark.parametrize("ws", ["generated_posts", "research_data", "content_briefs", "anything"])
@pytest.mark.parametrize("action", ["delete_row", "clear_sheet"])
def test_deleting_and_clearing_are_never_available(ws, action):
    assert check_agent_write(ws, action)


@pytest.mark.parametrize("ws,action", [
    ("generated_posts", "append_row"),            # how the generator hands its draft over
    ("generated_posts", "get_all_records"), ("generated_posts", "find_row_by_key"),
    ("research_data", "update_row"), ("content_briefs", "update_cell"), ("research_data", "append_row"),
])
def test_normal_pipeline_work_is_untouched(ws, action):
    assert check_agent_write(ws, action) is None


@pytest.fixture(scope="module")
def agents():
    for k in ("OPENROUTER_API_KEY", "GEMINI_API_KEY", "TAVILY_API_KEY"):
        os.environ.setdefault(k, "test")
    return importlib.import_module("blog_agent.blog_agents"), importlib.import_module("blog_agent.posting_agent")


def test_web_reading_agents_hold_the_restricted_tool_and_posting_keeps_the_full_one(agents):
    blog, posting = agents
    from tools.sheet_tool import manage_sheet_data_restricted_tool as restricted
    from tools.sheet_tool import manage_sheet_data_tool as full
    for agent in (blog.content_generator_agent, blog.content_evaluation_agent, blog.brief_agent):
        tools = list(agent.tools)
        assert restricted in tools and full not in tools, agent.name
    assert full in list(posting.posting_agent.tools) or any(
        t is full for a in (posting.preparation_agent, posting.posting_agent) for t in a.tools)


def test_the_restricted_tool_keeps_the_name_the_prompts_use(agents):
    from tools.sheet_tool import manage_sheet_data_restricted_tool
    assert manage_sheet_data_restricted_tool.name == "manage_sheet_data_tool"


def test_the_restricted_tool_refuses_before_touching_the_sheet_and_forces_raw_input(monkeypatch):
    import tools.sheet_tool as st
    calls = []
    monkeypatch.setattr(st, "manage_sheet_data", lambda **kw: calls.append(kw) or {"status": "success"})

    out = st.manage_sheet_data_restricted("generated_posts", "update_cell", row_index=2, col_index=9,
                                          row_values=["Approve"])
    assert out["status"] == "error" and calls == []                       # refused, sheet never reached

    ok = st.manage_sheet_data_restricted("research_data", "append_row", row_values=["=IMPORTDATA(\"http://x\")"])
    assert ok["status"] == "success" and calls[-1]["value_input_option"] == "RAW"


def test_its_schema_hides_retry_knobs_and_avoids_the_union_gemini_dislikes(agents):
    from tools.sheet_tool import manage_sheet_data_restricted_tool as t
    props = t.params_json_schema["properties"]
    assert not {"retries", "delay", "value_input_option"} & set(props)
    assert "anyOf" not in props["data"].get("items", {})
