"""Phase 1 §5.6 internal-link hardening — lib/linkguard + tools/linkguard_tool."""
import os

from lib.linkguard import (
    check_hygiene,
    classify_links,
    extract_links,
    inbound_counts,
    rescue_order,
)
from tools.linkguard_tool import check_link_hygiene, fetch_rescue_links

BASE = "https://owaisabdullah.dev"

GOOD_DRAFT = "\n".join(
    [
        "Intro with [guide A](https://owaisabdullah.dev/blog/guide-a) and "
        "[guide B](https://owaisabdullah.dev/blog/guide-b).",
        "More with [guide C](https://owaisabdullah.dev/blog/guide-c), "
        "[guide D](https://owaisabdullah.dev/blog/guide-d).",
        "Cite [Coffee Review](https://coffeereview.com/x) and "
        "[SCA](https://sca.coffee/y).",
        "One more internal [guide E](https://owaisabdullah.dev/blog/guide-e).",
    ]
)


def test_extract_and_classify_links():
    links = extract_links(GOOD_DRAFT)
    assert len(links) == 7
    classified = classify_links(links, base_url=BASE)
    assert len(classified["internal"]) == 5
    assert len(classified["external"]) == 2


def test_hygiene_pass_and_duplicate_anchor_detection():
    report = check_hygiene(GOOD_DRAFT, base_url=BASE)
    assert report["pass"] is True
    assert report["internal_count"] == 5 and report["external_count"] == 2
    assert report["duplicate_anchors"] == {}

    # same exact-match anchor 3x -> fails (max 2)
    spammy = " ".join(
        f"[best espresso machine](https://owaisabdullah.dev/blog/p{i})"
        for i in range(3)
    )
    bad = check_hygiene(spammy, base_url=BASE)
    assert bad["pass"] is False
    assert "best espresso machine" in bad["duplicate_anchors"]
    assert any("anchor diversity" in g for g in bad["guidance"])


def test_hygiene_flags_too_few_internal_links():
    only_external = "[NYT](https://nytimes.com/a) and [Guardian](https://theguardian.com/b)"
    report = check_hygiene(only_external, base_url=BASE)
    assert report["pass"] is False
    assert report["internal_count"] == 0
    assert any("3-8" in g for g in report["guidance"])


def test_inbound_counts_counts_other_posts_linking_in():
    source_hrefs = {
        "/blog/post-one": ["https://owaisabdullah.dev/blog/target-post", "https://x.com/a"],
        "/blog/post-two": ["https://other.host/blog/target-post"],
        "/blog/target-post": ["https://owaisabdullah.dev/blog/target-post"],
    }
    counts = inbound_counts(
        source_hrefs,
        ["/blog/target-post", "/blog/lonely"],
        self_slug="/blog/target-post",
    )
    # post-one + post-two hit; self link ignored
    assert counts["/blog/target-post"] == 2
    assert counts["/blog/lonely"] == 0


def test_rescue_order_puts_orphans_first_stable():
    candidates = [
        {"slug": "/blog/linked-3", "inbound": 5},
        {"slug": "/blog/zero", "inbound": 0},
        {"slug": "/blog/two", "inbound": 2},
        {"slug": "/blog/also-zero", "inbound": 0},
        {"slug": "/blog/linked-4", "inbound": 9},
    ]
    counts = {c["slug"]: c["inbound"] for c in candidates}
    ordered = rescue_order(candidates, counts)
    slugs = [c["slug"] for c in ordered]
    # needy first ascending; ties keep original relative order (stable)
    assert slugs == [
        "/blog/zero",
        "/blog/also-zero",
        "/blog/two",
        "/blog/linked-3",
        "/blog/linked-4",
    ]


def test_check_link_hygiene_tool_envelope():
    ok = check_link_hygiene(GOOD_DRAFT, base_url=BASE)
    assert ok["status"] == "ok" and ok["pass"] is True

    empty = check_link_hygiene("   ")
    assert empty["status"] == "error" and empty["pass"] is False


def test_fetch_rescue_links_degrades_without_env(monkeypatch):
    monkeypatch.delenv("SANITY_PROJECT_ID", raising=False)
    result = fetch_rescue_links("coffee makers", max_results=3)
    assert result["status"] == "error"
    assert result["links"] == []
    assert "Failed to fetch rescue links" in result["error"]


def test_generator_wires_link_hardening():
    from blog_agent.blog_agents import content_generator_agent

    instr = content_generator_agent.instructions
    assert "fetch_rescue_links_tool" in instr
    assert "check_link_hygiene_tool" in instr
    assert "Orphan rescue" in instr and "needs_rescue" in instr
    assert "3-8" in instr

    names = {getattr(t, "name", None) for t in content_generator_agent.tools}
    assert "fetch_rescue_links_tool" in names
    assert "check_link_hygiene_tool" in names
