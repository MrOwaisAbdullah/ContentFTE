"""Default LLM path for service.generate_content (§5.5) — the one place a
service operation may run a model, invoked lazily so REST/MCP startup stays
light (imported inside the call, never at module import).

Mirrors how scripts/run_stage.py runs the content stage (same agent,
same FallbackAgentRunner, same MAX_TURNS) but with an embedded brief:
the Article path composes the brief in-memory (lib/generation.py) instead
of reading content_briefs, so MCP/SDK generation works without Sheets.

Usage logging to model_usage_log rides the runner's own non-blocking path;
the model router itself is never edited (TASKS: routing refactor is last).
"""
from __future__ import annotations

from typing import Any

from lib.generation import MAX_TURNS
from lib.generation import render_prompt

LAST_USAGE: dict[str, Any] = {}


def _usage_from_result(result: Any) -> dict[str, Any]:
    """Aggregate token usage across the run's raw model responses.

    agents 0.19 RunResult has no .usage field; each raw ModelResponse does
    (openai-style prompt/completion tokens). Returns an empty dict when the
    runner shape carries no usage (fail-open: never blocks generation)."""
    responses = getattr(result, "raw_responses", None) or []
    requests = input_tokens = output_tokens = total_tokens = 0
    for resp in responses:
        usage = getattr(resp, "usage", None)
        if usage is None:
            continue
        requests += 1
        inp = getattr(usage, "prompt_tokens", None)
        if inp is None:
            inp = getattr(usage, "input_tokens", 0)
        out = getattr(usage, "completion_tokens", None)
        if out is None:
            out = getattr(usage, "output_tokens", 0)
        total = getattr(usage, "total_tokens", None) or (int(inp or 0) + int(out or 0))
        input_tokens += int(inp or 0)
        output_tokens += int(out or 0)
        total_tokens += int(total or 0)
    if not requests:
        return {}
    return {
        "requests": requests,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


async def generate_with_agent(brief: dict) -> str:
    """Run content_generator_agent on an in-memory brief; returns the raw
    final_output text (JSON envelope or raw Markdown — the service parses
    it via lib.generation.parse_generation_output). Raises on total
    runner failure; the service catches and turns that into {"error", "next"}.

    Stashes per-run token usage in LAST_USAGE for the caller (service)."""
    global LAST_USAGE
    LAST_USAGE = {}
    from dotenv import load_dotenv

    load_dotenv()

    from agents import set_tracing_disabled
    from agents.run import set_default_agent_runner

    from blog_agent.blog_agents import content_generator_agent, custom_runner

    # Same init as main.py/scripts/run_stage.py: all inference goes through
    # the custom fallback clients (never OpenAI's API), and nested runs
    # (e.g. the generator's get_evaluation_feedback tool) must go through
    # the same runner so model fallback + usage accounting apply.
    set_tracing_disabled(True)
    set_default_agent_runner(custom_runner)

    result = await custom_runner.run_with_fallback(
        content_generator_agent,
        render_prompt(brief),
        max_turns=MAX_TURNS,
    )
    LAST_USAGE = _usage_from_result(result)
    return str(getattr(result, "final_output", result))
