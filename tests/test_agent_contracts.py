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
