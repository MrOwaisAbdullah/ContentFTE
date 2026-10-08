"""lib.taxonomy — category/tag derivation for the Article → WP path (§5.11).

Pins the precedence and anti-drift rules:
    categories: brief/meta override > prefer-reuse lexical match vs existing
    > JEV Choice judge (stubbed here — never network) > title-cased
    propose-new. tags: deterministic only (keyword/title phrase + salient
    tokens, stopwords stripped, capped).

Offline by construction: every test injects a `jev=` stub, or relies on the
conftest env guard (OPENROUTER_API_KEY cleared → _jev_judge returns None).
"""
from lib import taxonomy as tax


def _no_jev(topic, existing):
    raise AssertionError("jev judge must not be called in this test")


# --- tags (deterministic) -----------------------------------------------------

def test_derive_tags_brief_wins():
    tags = tax.derive_tags(keyword="ai agent tools",
                           title="Something Else",
                           brief={"tags": ["Custom", "from brief"]})
    assert tags == ["Custom", "from brief"]


def test_derive_tags_phrase_plus_salient_tokens():
    tags = tax.derive_tags(keyword="ai agent tools",
                           title="AI Agent Tools: The Complete Guide")
    assert tags[0] == "ai agent tools"
    assert "ai" in tags and "agent" in tags and "tools" in tags
    # stopwords/filler never become tags
    assert not ({"guide", "complete", "the"} & set(t.lower() for t in tags))
    assert len(tags) <= tax.MAX_TAGS


def test_derive_tags_dedupes_case_insensitively_and_caps():
    tags = tax.derive_tags(keyword="seo tools", title="SEO Tools Best Picks",
                           max_tags=3)
    assert len(tags) <= 3
    lowered = [t.lower() for t in tags]
    assert len(lowered) == len(set(lowered))


def test_derive_tags_empty_topic_is_empty():
    assert tax.derive_tags(keyword="", title="") == []


# --- category resolution precedence -------------------------------------------

def test_lexical_prefers_reuse_over_any_jev_call():
    name, score = tax._lexical_match(
        "ai agent tools comparison", ["AI Agents", "Web Development"])
    assert name == "AI Agents" and score == 1.0  # containment: ai+agent ⊆ topic

    category, source = tax.resolve_category(
        keyword="ai agent tools", title="AI Agent Tools Guide",
        existing=["AI Agents", "Web Development"], jev=_no_jev)
    assert (category, source) == ("AI Agents", "lexical")


def test_lexical_match_scores_specificity_on_ties():
    name, _ = tax._lexical_match("ai agent tools", ["AI", "AI Agents"])
    # both fully contained; the more specific (2 tokens) wins deterministically
    assert name == "AI Agents"


def test_lexical_miss_falls_through_to_jev_reuse():
    calls = []

    def judge(topic, existing):
        calls.append(topic)
        return "Data Engineering"  # judge picks an existing name

    existing = ["Data Engineering", "Product News"]
    category, source = tax.resolve_category(
        keyword="etl pipelines", title="Best ETL Pipelines",
        existing=existing, jev=judge)
    assert (category, source) == ("Data Engineering", "jev_reuse")
    assert len(calls) == 1


def test_lexical_miss_jev_can_judge_a_new_name():
    def judge(topic, existing):
        return "Data Engineering"  # NOT in existing -> fresh, judged name

    category, source = tax.resolve_category(
        keyword="etl pipelines", title="",
        existing=["Product News"], jev=judge)
    assert (category, source) == ("Data Engineering", "jev_new")


def test_jev_failure_falls_back_to_propose_new():
    def judge(topic, existing):
        raise RuntimeError("jev down")

    category, source = tax.resolve_category(
        keyword="wp acceptance", title="", existing=["AI Agents"], jev=judge)
    assert (category, source) == ("Wp Acceptance", "new")


def test_no_existing_terms_skips_jev_entirely():
    category, source = tax.resolve_category(
        keyword="wp acceptance", title="", existing=[], jev=_no_jev)
    assert (category, source) == ("Wp Acceptance", "new")
    assert category == "wp acceptance".title()


def test_propose_new_prefers_keyword_then_title():
    assert tax._propose_new("wp acceptance", "WP Acceptance Post") == "Wp Acceptance"
    assert tax._propose_new("", "Only Title Here") == "Only Title Here"
    assert tax._propose_new("", "") == ""


# --- full derivation -----------------------------------------------------------

def test_derive_taxonomy_brief_override_short_circuits_everything():
    result = tax.derive_taxonomy(
        keyword="ai agent tools", title="Whatever",
        brief={"categories": ["SEO", "AI"], "tags": ["x"]},
        existing_categories=["AI Agents"],
        jev=_no_jev)  # neither lexical nor jev runs for supplied fields
    assert result["categories"] == ["SEO", "AI"]
    assert result["category_source"] == "brief"
    assert result["tags"] == ["x"]
    assert result["tag_source"] == "brief"


def test_derive_taxonomy_meta_override_is_second_in_line():
    result = tax.derive_taxonomy(
        keyword="kw", title="Title",
        brief={"categories": [], "tags": []},
        meta={"categories": ["From Meta"], "tags": ["meta-tag"]})
    assert result["categories"] == ["From Meta"]
    assert result["category_source"] == "meta"
    assert result["tags"] == ["meta-tag"]
    assert result["tag_source"] == "meta"


def test_derive_taxonomy_mixed_fields_derive_independently():
    result = tax.derive_taxonomy(
        keyword="ai agent tools", title="AI Agent Tools Guide",
        brief={"tags": ["brief-tag"]},
        existing_categories=["AI Agents"], jev=_no_jev)
    assert result["categories"] == ["AI Agents"]      # derived (lexical)
    assert result["category_source"] == "lexical"
    assert result["tags"] == ["brief-tag"]            # supplied
    assert result["tag_source"] == "brief"


def test_derive_taxonomy_never_empty_categories_with_a_topic():
    result = tax.derive_taxonomy(keyword="some topic", title="",
                                 existing_categories=[], jev=_no_jev)
    assert result["categories"] == ["Some Topic"]
    assert result["category_source"] == "new"


def test_derive_taxonomy_tolerates_none_inputs():
    result = tax.derive_taxonomy(keyword="", title="", brief=None, meta=None)
    assert result["categories"] == []   # no topic -> safety net downstream
    assert result["tags"] == []


def test_derive_taxonomy_caps_categories_and_tags():
    result = tax.derive_taxonomy(
        keyword="k", title="t",
        brief={"categories": ["A", "B", "C", "D"],
               "tags": ["1", "2", "3", "4", "5", "6"]})
    assert len(result["categories"]) == tax.MAX_CATEGORIES
    assert len(result["tags"]) == tax.MAX_TAGS


# --- JEV judge env gate ---------------------------------------------------------

def test_jev_judge_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert tax._jev_judge("topic", ["AI Agents"]) is None


def test_jev_judge_uses_key_and_swallows_errors(monkeypatch):
    import lib.jev_tools

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setattr(
        lib.jev_tools, "jev_classify_category",
        lambda topic, existing: '{"action": "reuse", "category": "AI Agents"}')
    assert tax._jev_judge("topic", ["AI Agents"]) == "AI Agents"

    def boom(topic, existing):
        raise RuntimeError("jev down")

    monkeypatch.setattr(lib.jev_tools, "jev_classify_category", boom)
    assert tax._jev_judge("topic", ["AI Agents"]) is None


def test_jev_judge_empty_existing_never_calls(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    def boom(topic, existing):
        raise AssertionError("no judgment without an existing taxonomy")

    import lib.jev_tools
    monkeypatch.setattr(lib.jev_tools, "jev_classify_category", boom)
    assert tax._jev_judge("topic", []) is None
