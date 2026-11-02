"""Plan PIPE-01 / PIPE-09 / PIPE-10: prompts and tools must agree.

Two production bugs had the same shape: a prompt told the model to call a tool by a name the
agent did not have (`factcheck_gate_tool` was registered as `run_factcheck_gate`; the brief
agent was told to use `manage_sheet_tool`, which never existed). The SDK answers such a call
with a tool-not-found error string, the model shrugs, and a "mandatory" step silently never
runs. Nothing checked it, so it shipped.

These tests import every agent module (no network, no model calls) and assert:
  1. every tool a prompt tells the model to call (backticked `*_tool`) exists on that agent;
  2. no tool schema declares an array without `items` (Gemini rejects it — the post_to_sanity
     `faqs` incident).
"""
from __future__ import annotations

import importlib
import os
import re

import pytest

agents_sdk = pytest.importorskip("agents")

MODULES = [
    "blog_agent.blog_agents",
    "blog_agent.research_agent",
    "blog_agent.posting_agent",
    "blog_agent.image_agent",
]
# `name` in backticks that looks like a tool: `get_brain_notes_tool`
_CALLED_TOOL_RE = re.compile(r"`([a-z][a-z0-9_]*_tool)`")


@pytest.fixture(scope="module")
def agents():
    os.environ.setdefault("OPENROUTER_API_KEY", "test")
    os.environ.setdefault("GEMINI_API_KEY", "test")
    os.environ.setdefault("TAVILY_API_KEY", "test")
    found = {}
    for module in MODULES:
        mod = importlib.import_module(module)
        for attr, val in vars(mod).items():
            if isinstance(val, agents_sdk.Agent):
                found[f"{module.rsplit('.', 1)[-1]}.{attr}"] = val
    assert len(found) >= 10, f"expected the pipeline's agents, found {sorted(found)}"
    return found


def test_every_tool_a_prompt_tells_the_model_to_call_exists_on_that_agent(agents):
    problems = []
    for key, agent in agents.items():
        instructions = agent.instructions if isinstance(agent.instructions, str) else ""
        available = {getattr(t, "name", "") for t in agent.tools}
        for name in sorted(set(_CALLED_TOOL_RE.findall(instructions))):
            if name not in available:
                problems.append(f"{key}: prompt says `{name}` but the agent has {sorted(available)}")
    assert not problems, "prompt/tool mismatch:\n" + "\n".join(problems)


def test_the_fact_check_gate_is_callable_under_the_name_the_writer_prompt_uses(agents):
    writer = agents["blog_agents.content_generator_agent"]
    assert "factcheck_gate_tool" in {t.name for t in writer.tools}
    assert "`factcheck_gate_tool`" in writer.instructions


def _array_nodes_without_items(node, path=""):
    if isinstance(node, dict):
        if node.get("type") == "array" and not node.get("items"):
            yield path or "<root>"
        for k, v in node.items():
            yield from _array_nodes_without_items(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _array_nodes_without_items(v, f"{path}[{i}]")


def test_no_tool_schema_declares_an_array_without_items(agents):
    bad = []
    seen = set()
    for agent in agents.values():
        for tool in agent.tools:
            if id(tool) in seen:
                continue
            seen.add(id(tool))
            schema = getattr(tool, "params_json_schema", None) or {}
            bad += [f"{tool.name}: {p}" for p in _array_nodes_without_items(schema)]
    assert not bad, "array parameters without `items` (rejected by Gemini):\n" + "\n".join(bad)


def test_the_contract_check_actually_detects_a_mismatch():
    """Guard against the test silently passing: a fake agent that names a missing tool fails it."""
    from agents import Agent, function_tool

    @function_tool
    def real_tool() -> str:
        return "x"

    ghost = Agent(name="ghost", instructions="Use `missing_tool` then `real_tool`.", tools=[real_tool])
    available = {t.name for t in ghost.tools}
    named = set(_CALLED_TOOL_RE.findall(ghost.instructions))
    assert named - available == {"missing_tool"}


def _nested_any_of(node, path="", depth=0):
    """Paths where an `anyOf` sits inside another `anyOf`/array/object parameter - the shape Gemini's schema
    converter chokes on (PIPE-10)."""
    out = []
    if isinstance(node, dict):
        if "anyOf" in node:
            for i, alt in enumerate(node["anyOf"]):
                if isinstance(alt, dict) and ("anyOf" in alt or (alt.get("type") == "array" and
                                              isinstance(alt.get("items"), dict) and
                                              ("anyOf" in alt["items"] or alt["items"].get("type") == "array"))):
                    out.append(f"{path or '<root>'}.anyOf[{i}]")
        for k, v in node.items():
            out += _nested_any_of(v, f"{path}.{k}" if path else k, depth + 1)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out += _nested_any_of(v, f"{path}[{i}]", depth + 1)
    return out


def test_no_tool_parameter_is_a_union_of_unions_or_a_union_containing_a_nested_array(agents):
    bad, seen = [], set()
    for agent in agents.values():
        for tool in agent.tools:
            if id(tool) in seen:
                continue
            seen.add(id(tool))
            bad += [f"{tool.name}: {p}" for p in _nested_any_of(getattr(tool, "params_json_schema", None) or {})]
    assert not bad, "nested unions in a tool schema (rejected by Gemini):\n" + "\n".join(bad)


def test_the_full_sheet_tool_takes_plain_text_data_and_hides_retry_knobs_from_the_model():
    from tools.sheet_tool import manage_sheet_data_tool
    props = manage_sheet_data_tool.params_json_schema["properties"]
    assert props["data"].get("type") == "string" or any(a.get("type") == "string" for a in props["data"].get("anyOf", []))
    assert "retries" not in props and "delay" not in props


def test_update_cells_data_arrives_as_json_text_and_reaches_the_sheet_as_rows(monkeypatch):
    import tools.sheet_tool as st
    seen = {}
    monkeypatch.setattr(st, "manage_sheet_data", lambda **kw: seen.update(kw) or {"status": "success"})
    fn = st.manage_sheet_data_tool.on_invoke_tool
    import asyncio, json
    from agents.tool_context import ToolContext
    args = json.dumps({"worksheet_name": "research_data", "action": "update_cells", "cell_range": "A1:B2",
                       "data": '[["a","b"],["c","d"]]'})
    asyncio.run(fn(ToolContext(None, tool_name="manage_sheet_data_tool", tool_call_id="t", tool_arguments=args), args))
    assert seen["data"] == [["a", "b"], ["c", "d"]]
    seen.clear()
    args = json.dumps({"worksheet_name": "generated_posts", "action": "update_cell", "row_index": 2, "col_index": 5, "data": "Yes"})
    asyncio.run(fn(ToolContext(None, tool_name="manage_sheet_data_tool", tool_call_id="t", tool_arguments=args), args))
    assert seen["data"] == "Yes"
