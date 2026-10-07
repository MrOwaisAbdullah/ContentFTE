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

from lib.generation import MAX_TURNS
from lib.generation import render_prompt


async def generate_with_agent(brief: dict) -> str:
    """Run content_generator_agent on an in-memory brief; returns the raw
    final_output text (JSON envelope or raw Markdown — the service parses
    it via lib.generation.parse_generation_output). Raises on total
    runner failure; the service catches and turns that into {"error", "next"}."""
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
    return str(getattr(result, "final_output", result))
