"""Plan SEO-02 / PIPE-01: the fact-check gate must not wave claims through.

The first matcher accepted a claim if its bare digits appeared ANYWHERE in the research
text ("5%" passed because "2025" contained a 5) and let "per" fire inside "experience".
"""
from __future__ import annotations

from lib.factcheck import ATTRIBUTION_RE, gate_factcheck, verify_claims, extract_claims

RESEARCH = [
    "Nespresso brews a cup in 30 seconds according to the 2024 review by CoffeeLab.",
    "The survey of 1,200 developers found that 62% of teams use agents in production.",
    "Published in 2025, the benchmark scored latency at 45 ms.",
]


def _unverified(md: str, excerpts=RESEARCH):
    return [c["claim"] for c in gate_factcheck(md, excerpts)["unverified"]]


def test_a_stray_digit_elsewhere_in_the_research_no_longer_grounds_a_claim():
    # "5%" is not in the research; the digit 5 only appears inside "2025" and "45".
    assert "5%" in _unverified("Teams cut costs by 5% after switching.")


def test_whole_number_with_matching_context_is_grounded():
    assert _unverified("A survey of 1200 developers found strong adoption.") == []
    assert _unverified("About 62% of teams run agents in production.") == []


def test_thousands_separators_are_normalised_both_ways():
    assert _unverified("The survey covered 1,200 developers.") == []
    assert _unverified("The survey covered 1200 developers.", ["Surveyed 1,200 developers in total."]) == []


def test_a_number_only_counts_near_words_from_its_own_sentence():
    # "62" exists in the research, but about teams — not about a battery.
    assert "62%" in _unverified("The battery lasts 62% longer than rivals.")


def test_numbers_do_not_match_inside_longer_numbers():
    assert "12" in _unverified("There were 12 launches.", ["There were 112 launches last year."])
    assert "45" in _unverified("There were 45 launches.", ["There were 245 launches last year."])
    assert _unverified("There were 12 launches.", ["There were 12 launches last year."]) == []


def test_attribution_verbs_match_on_word_boundaries():
    # "per" inside "experience"/"performance" must not read as an attribution.
    assert ATTRIBUTION_RE.search("Her experience Matters at 40% scale") is None
    assert ATTRIBUTION_RE.search("Strong performance Gains reached 3x") is None
    assert ATTRIBUTION_RE.search("per Gartner, adoption doubled") is not None
    # the named source must start with a capital letter or digit
    assert ATTRIBUTION_RE.search("according to some people it works") is None


def test_attribution_grounds_a_claim_only_when_the_source_name_is_in_the_research():
    named = "According to CoffeeLab, sales rose 80%."
    assert _unverified(named) == []                       # CoffeeLab is in the research
    unknown = "According to Acme Insights, sales rose 80%."
    assert "80%" in _unverified(unknown)                   # Acme is not
    generic = "According to the report, sales rose 80%."   # "report" is not a name
    assert "80%" in _unverified(generic)


def test_existing_behaviour_still_holds():
    out = gate_factcheck("Nespresso brews in 30 seconds and saves 40% of time.",
                         ["Nespresso brews in 30 seconds per review"])
    assert out["claim_count"] >= 1 and out["pass"] is False


def test_no_claims_passes_and_missing_research_fails_closed_per_claim():
    assert gate_factcheck("No numbers here at all.", RESEARCH)["pass"] is True
    res = verify_claims(extract_claims("Revenue grew 12% last quarter."), [])
    assert res["all_grounded"] is False
