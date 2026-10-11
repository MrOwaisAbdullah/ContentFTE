"""Post-stage image-failure hardening (live 2026-10-08 run).

The published log showed the featured-image path die on a Gemini 503
("model experiencing high demand") and ship a post that Sanity Studio
cannot publish: no mainImage, no alt. Four fixes, all asserted here:

1. Nested image agents are pinned to the reliable model (nested
   `.as_tool()` runs never see run_with_fallback's model chain).
2. The Preparation Agent retries `generate_image_tool` directly when
   `get_blog_image_tool` fails -- that path needs no LLM at all.
3. An AI in-post image is promoted into the featured slot rather than
   shipping imageless.
4. The pipeline no longer reports a false "Published".
"""
from __future__ import annotations

import os
import re


def _model_id(agent) -> str:
    model = getattr(agent, "model", None)
    return str(getattr(model, "model", "") or "")


def test_nested_image_agents_not_pinned_to_worst_model():
    """gemini-flash-latest is the fleet's 87.95%-error model (see
    custom_runner.LLM_MODELS comments), and gemini-3.5-flash* is retired
    (Google's 2026-10 deprecation notice). A nested agent's pinned model is
    its ONLY model -- run_with_fallback can't reach inside a tool call --
    so these must run on the reliable lite model."""
    from blog_agent.image_agent import (
        contextual_image_insertion_agent,
        image_quality_evaluation_agent,
        image_selection_agent,
    )
    from blog_agent.posting_agent import posting_agent, preparation_agent

    for agent in (contextual_image_insertion_agent, image_quality_evaluation_agent,
                  image_selection_agent, preparation_agent, posting_agent):
        assert _model_id(agent) == "gemini-3.1-flash-lite", (
            f"{agent.name} still pinned to {_model_id(agent)!r} -- nested "
            "agents get no fallback, so the pin IS the fallback"
        )


def test_preparation_agent_retries_llm_free_generator_on_failure():
    from blog_agent.posting_agent import preparation_agent

    tools = {getattr(t, "name", None) for t in preparation_agent.tools}
    assert "generate_image_tool" in tools, (
        "featured retry has no LLM-free entry point"
    )
    instr = preparation_agent.instructions
    # ordered ladder, not the old straight-to-empty fallback
    assert "get_blog_image_tool" in instr
    assert "`generate_image_tool(keyword=" in instr
    assert "NO LLM call" in instr
    assert "Never go straight to step 2" in instr
    # stock must still never fill the featured slot
    assert "stock never fills the featured slot" in instr


def test_promote_inpost_ai_image_prefers_local_ai_over_stock(tmp_path):
    from tools.tools import _promote_inpost_ai_image

    ai = tmp_path / "tmpai.png"
    ai.write_bytes(b"fake")
    content = (
        "text ![stock one](https://images.pexels.com/photos/1/x.jpeg) "
        f"more ![ai one]({ai.as_posix()}) tail"
    )
    path, alt = _promote_inpost_ai_image(content)
    assert os.path.normpath(path) == str(ai) and alt == "ai one"  # stock skipped, AI promoted


def test_promote_inpost_ai_image_never_promotes_stock():
    from tools.tools import _promote_inpost_ai_image

    stock_only = "![alt](https://images.pexels.com/photos/1/x.jpeg?auto=compress)"
    assert _promote_inpost_ai_image(stock_only) == (None, None)
    # protocol-relative counts as remote too
    assert _promote_inpost_ai_image("![alt](//cdn.example/x.jpg)") == (None, None)
    # no images at all
    assert _promote_inpost_ai_image("plain body text") == (None, None)
    assert _promote_inpost_ai_image("") == (None, None)


def test_promote_inpost_ai_image_skips_missing_local_files():
    from tools.tools import _promote_inpost_ai_image

    ghost = os.path.join(os.sep, "nonexistent", "tmp_ghost.png")
    assert _promote_inpost_ai_image(f"![ghost]({ghost})") == (None, None)


def test_post_tool_result_flags_draft_and_needs_image():
    from tools.tools import post_to_sanity_tool

    src = open(os.path.join("tools", "tools.py"), encoding="utf-8").read()
    assert '"doc_state": "draft"' in src
    assert '"needs_image": not bool(result.get("image_id"))' in src


def test_run_post_reports_needs_image_honestly():
    src = open(os.path.join("scripts", "run_stage.py"), encoding="utf-8").read()
    assert 'if result.get("needs_image"):' in src
    assert "Studio blocks publishing it" in src
    assert 'f"🌐 Published **{title}**' in src  # the honest branch still exists


def test_posting_agent_instructions_do_not_claim_published_when_no_image():
    from blog_agent.posting_agent import posting_agent

    instr = posting_agent.instructions
    assert "needs_image" in instr
    assert "do NOT report it as published" in instr
