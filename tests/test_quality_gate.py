"""Plan SEO-01 / SEO-02 / SEO-24: the deterministic quality gate and AEO lint."""
from __future__ import annotations

from lib import aeo_lint
from lib.quality_gate import assess

FULL_SUBS = {k: 85 for k in ("accuracy", "depth", "seo", "voice", "originality", "citability")}
RESEARCH = ["A survey of 1,200 developers found 62% of teams use agents in production (CoffeeLab, 2024)."]
CLEAN = "A survey of 1200 developers found strong adoption of agents in production."


def _meta(**kw):
    base = {"generation": {"checks": {"words": {"pass": True}, "tldr": {"pass": True}}},
            "scores": {"overall": 95, "sub_scores": dict(FULL_SUBS)}}
    base.update(kw)
    return base


def test_clean_article_passes_with_no_blockers():
    out = assess(content_md=CLEAN, meta=_meta(), source_excerpts=RESEARCH, check_links=False)
    assert out["pass"] is True and out["blocking"] == []
    assert out["checks"]["factcheck"]["pass"] is True


def test_failed_generation_check_blocks_and_says_why():
    meta = _meta()
    meta["generation"]["checks"]["words"] = {"pass": False, "value": 430, "need": 900}
    out = assess(content_md=CLEAN, meta=meta, source_excerpts=RESEARCH, check_links=False)
    assert out["pass"] is False
    assert any("'words'" in b and "430 vs 900" in b for b in out["blocking"])


def test_unsupported_claim_blocks_when_research_exists():
    out = assess(content_md="Costs fell 73% after the switch.", meta=_meta(),
                 source_excerpts=RESEARCH, check_links=False)
    assert out["pass"] is False
    assert any("73%" in b for b in out["blocking"])
    assert out["checks"]["factcheck"]["unverified"] == 1


def test_no_research_on_file_warns_instead_of_blocking():
    out = assess(content_md="Costs fell 73% after the switch.", meta=_meta(),
                 source_excerpts=[], check_links=False)
    assert out["pass"] is True
    assert any("could not be fact-checked" in w for w in out["warnings"])
    assert out["checks"]["factcheck"]["skipped"] == "no research on file"


def test_eval_gate_floor_is_enforced_when_subscores_are_recorded():
    meta = _meta()
    meta["scores"]["sub_scores"]["accuracy"] = 60
    out = assess(content_md=CLEAN, meta=meta, source_excerpts=RESEARCH, check_links=False)
    assert out["pass"] is False
    assert any("eval gate" in b and "accuracy=60" in b for b in out["blocking"])


def test_missing_subscores_cannot_be_enforced_so_they_warn():
    meta = {"scores": {"overall": 72}}
    out = assess(content_md=CLEAN, meta=meta, source_excerpts=RESEARCH, check_links=False)
    assert out["pass"] is True
    assert any("below 90" in w for w in out["warnings"])
    assert out["checks"]["eval"]["skipped"] == "sub-scores not recorded"


def test_legacy_article_without_generation_checks_is_not_blocked_for_it():
    out = assess(content_md=CLEAN, meta={}, source_excerpts=RESEARCH, check_links=False)
    assert out["checks"]["draft"]["skipped"].startswith("no generation checks")
    assert out["pass"] is True


def test_broken_links_block_but_bot_blocked_links_only_warn():
    md = "See [a](https://ok.example/x), [b](https://dead.example/y) and [c](https://walled.example/z)."
    status = {"https://ok.example/x": (True, 200), "https://dead.example/y": (False, 404),
              "https://walled.example/z": (False, 403)}
    out = assess(content_md=md, meta=_meta(), source_excerpts=RESEARCH, check_links=True,
                 head_fn=lambda u: status[u])
    assert out["pass"] is False
    assert out["checks"]["links"]["broken"] == [{"url": "https://dead.example/y", "status": 404}]
    assert any("dead.example" in b for b in out["blocking"])
    assert not any("walled.example" in b for b in out["blocking"])
    assert any("could not be verified" in w for w in out["warnings"])


def test_link_check_is_off_by_default(monkeypatch):
    monkeypatch.delenv("QUALITY_GATE_CHECK_LINKS", raising=False)

    def boom(_):  # would fail the test if the network check ran
        raise AssertionError("link check must not run by default")

    out = assess(content_md="See [a](https://x.example/p).", meta=_meta(),
                 source_excerpts=RESEARCH, head_fn=boom)
    assert "skipped" in out["checks"]["links"]


# ---------------------------------------------------------------- AEO lint
LONG = " ".join(["filler"] * 650)


def _ids(md, faqs=None):
    return {f["id"] for f in aeo_lint.lint(md, faqs)}


def test_tldr_length_outside_40_to_60_words_warns():
    short = "TL;DR: Agents help teams ship faster.\n\n## What is it?\nBody."
    assert "tldr_length" in _ids(short)
    ok = "TL;DR: " + " ".join(["word"] * 50) + "\n\n## What is it?\nBody."
    assert "tldr_length" not in _ids(ok)


def test_question_headings_ratio():
    md = "## Overview of agents\nx\n## Architecture notes\nx\n## Deployment guide\nx\n"
    assert "question_headings" in _ids(md)
    good = "## What is an agent?\nx\n## How do handoffs work?\nx\n## Architecture notes\nx\n"
    assert "question_headings" not in _ids(good)


def test_comparison_section_needs_a_table():
    no_table = "## Agents vs workflows\n- agents: flexible\n- workflows: predictable\n"
    assert "comparison_table" in _ids(no_table)
    table = "## Agents vs workflows\n| a | b |\n|---|---|\n| 1 | 2 |\n"
    assert "comparison_table" not in _ids(table)


def test_faq_emitted_twice_is_flagged():
    md = ("## How do I install it?\nRun pip.\n## What is a handoff?\nA transfer.\n"
          "## Frequently Asked Questions\n")
    faqs = [{"question": "How do I install it?", "answer": "pip"},
            {"question": "What is a handoff?", "answer": "transfer"}]
    assert "faq_duplicated" in _ids(md, faqs)
    assert "faq_duplicated" not in _ids("## Intro\ntext\n", faqs)


def test_attribution_and_source_quality_only_judged_on_long_posts():
    short = "A short post with 40% growth."
    assert "attributed_numbers" not in _ids(short)
    weak = (LONG + "\n\nGrowth hit 40% (unsourced).\n\n## Sources\n"
            "- [a](https://medium.com/x)\n- [b](https://youtube.com/y)\n- [c](https://reddit.com/r/z)\n")
    ids = _ids(weak)
    assert "attributed_numbers" in ids and "weak_sources" in ids
    strong = (LONG + "\n\nAccording to CoffeeLab, growth hit 40%.\nPer Gartner, 62% adopted.\n\n## Sources\n"
              "- [a](https://docs.example.com/x)\n- [b](https://arxiv.org/abs/1)\n- [c](https://vendor.io/y)\n")
    assert not ({"attributed_numbers", "weak_sources", "source_domains"} & _ids(strong))


def test_all_lint_findings_are_warnings_never_blockers():
    for f in aeo_lint.lint("## Agents vs workflows\nplain\n"):
        assert f["severity"] == "warn"
