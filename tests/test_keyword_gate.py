"""Pure sanity-check of the keyword gate before it is wired into the pipeline."""
from lib.seo_keywords import (
    MAX_SECONDARY,
    check_keywords,
    keyword_placement,
    min_uses,
    parse_keywords,
    split_markdown,
)

DRAFT = """# Best Coffee Maker for Small Kitchens

> **TL;DR** - A compact coffee maker fits a small kitchen if it stays under
12 inches wide, which is what most counters actually allow.

## Why the compact coffee maker wins

A compact coffee maker is the single biggest space saver on a cramped counter.
Most people buy the largest machine that fits, then live around it. A small
coffee maker with a thermal carafe keeps the counter clear and the coffee
hot, and it costs less to run.

## What to look for in a small coffee maker

Width first, then a permanent filter. A small coffee maker with a swing-out
basket is easier to clean than one you have to lift out sideways.

## Sources

- Coffee Review
"""


def test_parse_handles_all_separators_and_dedupes():
    kws, warnings = parse_keywords("compact coffee maker; small coffee maker\n"
                                   "best small coffee maker, compact coffee maker")
    assert len(kws) == 3
    assert any("duplicate" in w for w in warnings)


def test_parse_caps_secondaries_and_reports_drops():
    cell = ", ".join(f"kw number {i}" for i in range(6))
    kws, warnings = parse_keywords(cell)
    assert len(kws) == MAX_SECONDARY
    assert any("cap is" in w for w in warnings)


def test_parse_primary_keeps_only_the_first_value():
    kws, warnings = parse_keywords("coffee maker, espresso machine",
                                   kind="primary")
    assert kws == ["coffee maker"]
    assert any("only the first" in w for w in warnings)


def test_parse_empty_and_overlong():
    assert parse_keywords("")[0] == []
    long_kw = "x" * 80
    kws, warnings = parse_keywords(long_kw)
    assert kws == [] and any("longer than" in w for w in warnings)


def test_min_uses_scales_with_phrase_length():
    assert min_uses("coffee maker") == 2
    # 7 words: too long to weave in twice without stuffing
    assert min_uses("the compact coffee maker for a very small kitchen") == 1
    assert min_uses(" ".join(["word"] * 12)) == 0   # topic, never gated


def test_placement_separates_headings_from_body():
    slots = split_markdown(DRAFT)
    assert slots["title"] == "Best Coffee Maker for Small Kitchens"
    assert not slots["headings"] or all(slots["headings"])
    p = keyword_placement(DRAFT, "compact coffee maker")
    assert p["in_headings"] >= 1 and p["in_body"] >= 2
    assert p["total"] == p["in_title"] + p["in_headings"] + p["in_body"]


def test_matching_tolerates_hyphens_and_case():
    # TL;DR, one H2 and one body sentence in the draft
    p = keyword_placement(DRAFT, "Compact Coffee-Maker")
    assert p["in_title"] == 0
    assert p["in_headings"] == 1 and p["in_body"] == 2
    assert p["total"] == 3


def test_gate_passes_when_keywords_are_present():
    out = check_keywords(DRAFT, primary="coffee maker",
                         secondary=["compact coffee maker", "small coffee maker"])
    assert out["checked"] is True
    assert out["pass"] is True, out["guidance"]
    assert out["missing"] == []


def test_gate_fails_with_actionable_report():
    # primary lands in the title + one heading (passes), both secondaries are
    # absent -> only those two are reported missing.
    draft = ("# Best Coffee Maker for Small Kitchens\n\n"
             "## Why the coffee maker you pick matters\n\nA machine.\n")
    out = check_keywords(draft, primary="coffee maker",
                         secondary=["thermal carafe", "small coffee maker"])
    assert out["pass"] is False
    assert set(out["missing"]) == {"thermal carafe", "small coffee maker"}
    joined = " ".join(out["guidance"])
    assert "thermal carafe" in joined and "needs 2" in joined
    assert "one H2/H3 heading plus 1-2 natural body sentences" in joined
    # the primary that passed is not listed as missing
    assert "coffee maker" not in out["missing"]


def test_gate_reports_a_missing_primary_too():
    draft = "# Best Coffee Maker for Small Kitchens\n\n## Why it matters\n\nA machine.\n"
    out = check_keywords(draft, primary="coffee maker",
                         secondary=["compact coffee maker"])
    # both absent here; the point is the primary is reported with its role
    assert set(out["missing"]) == {"coffee maker", "compact coffee maker"}
    primary_notes = [g for g in out["guidance"] if g.startswith("primary keyword")]
    assert primary_notes and "coffee maker" in primary_notes[0]
    assert any(g.startswith("secondary keyword") for g in out["guidance"])


def test_gate_fails_open_when_no_keywords_supplied():
    out = check_keywords("Anything at all.", primary="", secondary=[])
    assert out["checked"] is False
    assert out["pass"] is True and out["guidance"] == []


def test_density_warning_reports_stuffing():
    # needs to be long enough that a fixed share means real repetition
    para = ("The coffee maker is the best coffee maker because a coffee maker "
            "saves time. ") * 12
    stuffed = f"# T\n\n{para}"
    assert len(para.split()) > 60
    out = check_keywords(stuffed, primary="coffee maker")
    assert out["pass"] is True          # count passes
    assert any("stuffing" in g or "uses, cap" in g for g in out["guidance"])


def test_density_does_not_flag_compact_drafts():
    """0.8% of a 130-word body is one use; a compact buyer-intent page must
    not be branded as keyword stuffing for two natural mentions."""
    compact = ("# T\n\n## Why it matters\n\nA compact coffee maker saves space. "
               "A small coffee maker is cheaper to run.\n")
    out = check_keywords(compact, primary="coffee maker")
    assert out["pass"] is True
    assert out["guidance"] == []


def test_partial_use_fails_on_secondary_only():
    draft = ("# Best Coffee Maker\n\n"
             "## Why the compact coffee maker wins\n\n"
             "A compact coffee maker is the space saver. Everything else is filler "
             "that goes on for a while to make the body long enough to matter.\n")
    out = check_keywords(draft, primary="coffee maker",
                         secondary=["compact coffee maker", "thermal carafe"])
    assert out["missing"] == ["thermal carafe"]
    assert out["pass"] is False
