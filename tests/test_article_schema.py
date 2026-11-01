"""Plan SEO-07 / SEO-08 / SEO-19: real Article structured data and an honest dateModified."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from lib import freshness
from lib.geo import (article_schema, build_article_graph, identity_from_settings,
                     organization_node, person_node)

AUTHOR = {"name": "Ada Lovelace", "url": "https://x.test/about", "same_as": ["https://github.com/ada"],
          "job_title": "Engineer"}
PUBLISHER = {"name": "X Labs", "url": "https://x.test", "logo_url": "https://x.test/logo.png",
             "logo_width": 512, "logo_height": 512}


# ----------------------------------------------------------------- article_schema
def test_original_call_shape_is_unchanged_and_adds_nothing_invented():
    out = article_schema("T", "https://x.test/p", "2026-01-01T00:00:00+00:00")
    assert out["@type"] == "Article" and out["headline"] == "T" and out["url"] == "https://x.test/p"
    assert out["dateModified"] == "2026-01-01T00:00:00+00:00"        # no longer "now"
    for absent in ("author", "publisher", "image", "keywords", "wordCount", "description"):
        assert absent not in out, f"{absent} must not appear without real data"
    assert out["mainEntityOfPage"] == {"@type": "WebPage", "@id": "https://x.test/p"}


def test_enrichment_adds_only_what_was_supplied():
    out = article_schema("T", "https://x.test/p", "2026-01-01", "2026-03-01", author=AUTHOR,
                         publisher=PUBLISHER, image="https://x.test/i.jpg", description=" Short. ",
                         keywords=["agents", "", "mcp"], word_count=1800, in_language="en")
    assert out["author"] == {"@type": "Person", "name": "Ada Lovelace", "url": "https://x.test/about",
                             "sameAs": ["https://github.com/ada"], "jobTitle": "Engineer"}
    assert out["publisher"]["logo"] == {"@type": "ImageObject", "url": "https://x.test/logo.png",
                                        "width": 512, "height": 512}
    assert out["image"] == {"@type": "ImageObject", "url": "https://x.test/i.jpg"}
    assert (out["description"], out["keywords"], out["wordCount"]) == ("Short.", "agents, mcp", 1800)
    assert out["dateModified"] == "2026-03-01"


def test_an_author_without_a_name_is_never_fabricated():
    assert person_node(None) is None
    assert person_node({"url": "https://x.test"}) is None
    assert person_node({"name": "  "}) is None
    assert organization_node({"url": "https://x.test"}) is None
    assert "author" not in article_schema("T", "u", author={"url": "https://x.test"})


def test_identity_publisher_falls_back_to_the_site_but_author_does_not():
    ident = identity_from_settings({}, "My Site", "https://my.test")
    assert ident["author"] is None
    assert ident["publisher"] == {"name": "My Site", "url": "https://my.test"}
    configured = identity_from_settings({"identity": {"author": AUTHOR, "publisher": PUBLISHER}}, "S", "u")
    assert configured["author"]["name"] == "Ada Lovelace" and configured["publisher"]["name"] == "X Labs"


# ----------------------------------------------------------------- @graph
def test_graph_links_entities_by_id_and_defines_each_once():
    g = build_article_graph(title="T", url="https://x.test/blog/p", site_url="https://x.test",
                            date_published="2026-01-01", date_modified="2026-02-01", description="d",
                            author=AUTHOR, publisher=PUBLISHER, image="https://x.test/i.jpg",
                            keywords=["a"], word_count=900,
                            faqs=[{"question": "Q?", "answer": "A."}])
    assert g["@context"] == "https://schema.org"
    by_type = {n["@type"]: n for n in g["@graph"]}
    assert set(by_type) == {"Organization", "Person", "WebSite", "WebPage", "ImageObject",
                            "BlogPosting", "BreadcrumbList", "FAQPage"}
    post = by_type["BlogPosting"]
    assert post["author"] == {"@id": "https://x.test/#person"}
    assert post["publisher"] == {"@id": "https://x.test/#organization"}
    assert post["image"] == {"@id": "https://x.test/blog/p#primaryimage"}
    assert post["dateModified"] == "2026-02-01" != post["datePublished"]
    ids = [n["@id"] for n in g["@graph"]]
    assert len(ids) == len(set(ids))                                   # each entity defined once
    # every @id reference resolves to a node in the graph
    refs = {v["@id"] for n in g["@graph"] for v in n.values()
            if isinstance(v, dict) and set(v) == {"@id"}}
    assert refs <= set(ids)
    crumbs = by_type["BreadcrumbList"]["itemListElement"]
    assert [c["position"] for c in crumbs] == [1, 2, 3] and all(c["name"] for c in crumbs)


def test_graph_omits_nodes_it_has_no_data_for():
    g = build_article_graph(title="T", url="https://x.test/p", site_url="https://x.test")
    types = {n["@type"] for n in g["@graph"]}
    assert "Person" not in types and "Organization" not in types and "ImageObject" not in types
    assert "FAQPage" not in types
    post = next(n for n in g["@graph"] if n["@type"] == "BlogPosting")
    assert "author" not in post and "publisher" not in post and "image" not in post


def test_headline_is_capped_at_googles_110_characters():
    g = build_article_graph(title="x" * 300, url="https://x.test/p", site_url="https://x.test")
    assert len(next(n for n in g["@graph"] if n["@type"] == "BlogPosting")["headline"]) == 110


# ----------------------------------------------------------------- freshness
BASE = " ".join(f"word{i}" for i in range(400))


def test_whitespace_and_tiny_edits_are_not_updates():
    assert freshness.substantive_change(BASE, BASE) is False
    assert freshness.substantive_change(BASE, BASE.replace(" word7 ", "  word7\n")) is False
    assert freshness.substantive_change(BASE, BASE + " extra") is False         # 1 word of 400


def test_real_rewrites_are_updates():
    edited = BASE.replace("word10", "fresh").replace("word50", "new").replace("word90", "data")
    assert freshness.substantive_change(BASE, " ".join(["new paragraph of facts"] * 20) + " " + BASE)
    assert freshness.change_ratio(BASE, "completely different text") > 0.9
    assert freshness.change_ratio(BASE, edited) < freshness.change_ratio(BASE, "different")


def test_bump_modified_only_when_substantive_and_never_mutates_input():
    meta = {"keep": 1}
    same = freshness.bump_modified(meta, BASE, BASE + " typo")
    assert "modified_at" not in same and meta == {"keep": 1}
    now = datetime(2026, 11, 1, tzinfo=timezone.utc)
    bumped = freshness.bump_modified(meta, BASE, "totally rewritten " * 100, now=now)
    assert bumped["modified_at"] == now.isoformat() and bumped["keep"] == 1


def test_effective_modified_never_precedes_publication():
    pub, created = "2026-05-01T00:00:00+00:00", "2026-04-01T00:00:00+00:00"
    assert freshness.effective_modified({}, pub, created) == pub
    assert freshness.effective_modified({"modified_at": "2026-06-01T00:00:00+00:00"}, pub, created) \
        == "2026-06-01T00:00:00+00:00"
    assert freshness.effective_modified({"modified_at": "2026-01-01T00:00:00+00:00"}, pub, created) == pub
    assert freshness.effective_modified(None, None, created) == created


# ----------------------------------------------------------------- service integration
@pytest.fixture
def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'schema.db'}")
    import lib.db as db
    if db._engine is not None:
        db._engine.dispose()
    db._engine = None
    db._SessionLocal = None
    from sdk import service
    service.init()
    yield service
    if db._engine is not None:
        db._engine.dispose()
    db._engine = None
    db._SessionLocal = None


def _published_article(svc, settings=None):
    from lib.db import Article, get_session
    svc.upsert_site("schema-site", "Schema Site", "custom", "https://schema.test", settings or {})
    art = svc.submit_article("schema-site", keyword="schema kw")
    published = datetime.now(timezone.utc) - timedelta(days=60)
    s = get_session()
    try:
        a = s.get(Article, art["id"])
        a.content_md = BASE
        a.status = "published"
        a.published_at = published
        a.meta = {**(a.meta or {}), "summary": "A summary."}
        s.commit()
    finally:
        s.close()
    return art["id"], published


def test_payload_omits_author_until_the_site_configures_one(svc):
    aid, published = _published_article(svc)
    article = svc.get_article(aid, include_content=True)["schema"]["article"]
    assert "author" not in article
    assert article["publisher"]["name"] == "Schema Site"                # real site name, not invented
    assert article["datePublished"] == article["dateModified"] == published.isoformat()
    assert article["description"] == "A summary." and article["wordCount"] == 400


def test_configured_identity_flows_into_the_delivery_payload(svc):
    aid, _ = _published_article(
        svc, {"identity": {"author": AUTHOR, "publisher": PUBLISHER}})
    article = svc.get_article(aid, include_content=True)["schema"]["article"]
    assert article["author"]["name"] == "Ada Lovelace" and article["author"]["sameAs"]
    assert article["publisher"]["logo"]["url"] == "https://x.test/logo.png"


def test_date_modified_moves_only_on_a_substantive_edit(svc):
    aid, published = _published_article(svc)
    svc.update_content(aid, BASE + " typo")                              # not substantive
    assert svc.get_article(aid, include_content=True)["schema"]["article"]["dateModified"] \
        == published.isoformat()
    svc.update_content(aid, "A completely rewritten and updated article. " * 120)
    modified = svc.get_article(aid, include_content=True)["schema"]["article"]["dateModified"]
    assert modified > published.isoformat()
    assert datetime.fromisoformat(modified) > datetime.now(timezone.utc) - timedelta(minutes=5)
