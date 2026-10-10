"""Model fleet hygiene.

Guards the two things that silently break production runs:

1. A DEPRECATED model still in the fleet -- gemini-3.5-flash / -lite were
   retired by Google's 2026-10 deprecation notice (requests route to 3.6), so
   an entry that survives there burns a fallback slot on a dead model.
2. OpenRouter's free quota being treated as per-model -- it is ONE shared
   account-level allowance, so three entries billed as 50/day each would let a
   single run make 150 calls and get rate-limited on the third.

Also asserts that adding a free model to OPENROUTER_FREE_MODELS needs no other
edit: the group, the quota tables and the availability check all follow it.
"""
from __future__ import annotations

import asyncio


def _fleet():
    """The runner WITHOUT touching Google Sheets: build the shape
    is_model_available needs and nothing else."""
    from blog_agent import custom_runner

    runner = object.__new__(custom_runner.FallbackAgentRunner)
    runner.LLM_MODELS = (
        [{"name": m["name"], "model": m["model"], "provider": m["provider"]}
         for m in [
            *[{"name": n, "model": n, "provider": "gemini"} for n in
              ("gemini-3.1-flash-lite", "gemini-3.6-flash", "gemma-4-26b-a4b-it")],
            {"name": "deepseek-v4-flash", "model": "deepseek/deepseek-v4-flash-0731",
             "provider": "openrouter-paid"},
            *custom_runner._openrouter_free_entries(),
         ]]
    )
    runner.SHARED_QUOTA_GROUPS = custom_runner._openrouter_free_shared_quota()
    runner.model_limits = {
        "gemini-3.1-flash-lite": 500,
        "gemini-3.6-flash": 20,
        "gemma-4-26b-a4b-it": 14400,
        "deepseek-v4-flash": 1000,
        **{e["name"]: custom_runner.OPENROUTER_FREE_SHARED_RPD
           for e in custom_runner._openrouter_free_entries()},
    }
    runner.model_rpm_limits = {
        "gemini-3.1-flash-lite": 15,
        "gemini-3.6-flash": 5,
        "gemma-4-26b-a4b-it": 30,
        "deepseek-v4-flash": 60,
        **{e["name"]: custom_runner.OPENROUTER_FREE_RPM
           for e in custom_runner._openrouter_free_entries()},
    }
    runner.model_usage = {m["name"]: 0 for m in runner.LLM_MODELS}
    runner.rpm_timestamps = {m["name"]: [] for m in runner.LLM_MODELS}
    runner.provider_unavailable_until = {m["name"]: None for m in runner.LLM_MODELS}
    runner.last_reset = __import__("datetime").datetime.now()
    return runner


def test_no_deprecated_model_in_the_fleet():
    from blog_agent import custom_runner

    ids = [e["model"] for e in custom_runner._openrouter_free_entries()]
    retired = ("gemini-3.5-flash", "gemini-3.5-flash-lite")
    for bad in retired:
        assert not any(bad == m or m.startswith(bad + "-") for m in ids), (
            f"{bad} is retired (Google 2026-10 notice) but still listed")


def test_openrouter_free_models_share_one_quota():
    runner = _fleet()
    from blog_agent import custom_runner

    members = [e["name"] for e in custom_runner._openrouter_free_entries()]
    assert len(members) >= 2, "the shared-quota rule needs 2+ free models to test"

    limit = custom_runner.OPENROUTER_FREE_SHARED_RPD
    group = runner.SHARED_QUOTA_GROUPS["openrouter-free"]
    assert group["rpd"] == limit
    assert group["members"] == members

    # burn the whole allowance on the FIRST free model only
    runner.model_usage[members[0]] = limit
    for name in members[1:]:
        assert asyncio.run(runner.is_model_available(name)) is False, (
            f"{name} reads as available while the shared allowance is spent "
            "-- OpenRouter's free quota is account-level, not per-model")


def test_shared_quota_still_allows_the_first_calls():
    runner = _fleet()
    members = [e["name"] for e in
               __import__("blog_agent.custom_runner", fromlist=["x"])
               ._openrouter_free_entries()]
    runner.model_usage[members[0]] = 1
    assert asyncio.run(runner.is_model_available(members[0])) is True


def test_every_fleet_model_has_quota_entries():
    """Adding an entry to LLM_MODELS without a quota row would make
    is_model_available read 0 and silently disable the model."""
    from blog_agent import custom_runner

    entries = [*custom_runner._openrouter_free_entries()]
    names = [e["name"] for e in entries]
    assert names, "the free-model list must not be empty"
    for name in names:
        assert name in custom_runner._openrouter_free_shared_quota()["openrouter-free"]["members"]

    # the group is derived, never a second hand-maintained list
    src = _read("blog_agent", "custom_runner.py")
    assert "SHARED_QUOTA_GROUPS" in src
    assert "_openrouter_free_shared_quota()" in src
    assert src.count("OPENROUTER_FREE_MODELS") >= 3  # const, comment, helper


def _read(*parts: str) -> str:
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, *parts), encoding="utf-8") as fh:
        return fh.read()
