"""Phase 1 engine tests — no network, no LLM, no model-router touches."""
import os

import pytest

TEST_DB = "sqlite:///./test_contentfte_phase1.db"


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch):
    # C: is full (0 bytes free) so pytest's default tmp_path (under
    # C:\Users\...\Temp) cannot create dirs. Keep test state on D:
    # (repo drive) instead — no tmp_path fixture used at all.
    workdir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            ".test-tmp-phase1")
    os.makedirs(workdir, exist_ok=True)
    db_file = os.path.join(workdir, "t.db")
    try:
        os.remove(db_file)
    except OSError:
        pass
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("SEO_DATA_PROVIDER", "off")
    import lib.db as db

    # dispose BEFORE deleting — Windows can't unlink a DB file an open
    # pool connection still holds.
    if db._engine is not None:
        db._engine.dispose()
    db._engine = None
    db._SessionLocal = None
    try:
        os.remove(db_file)
    except OSError:
        pass
    db.init_db()
    yield
    if db._engine is not None:
        db._engine.dispose()
    try:
        os.remove(db_file)
    except OSError:
        pass


def _site(session, slug="acme"):
    from lib.db import Site

    site = Site(slug=slug, name=slug.title(), site_type="wordpress",
                base_url="https://example.com")
    session.add(site)
    session.commit()
    session.refresh(site)
    return site


def test_ledger_lifecycle_and_priority():
    from lib.db import get_session
    from lib.ledger import (briefable_rows, check_cannibalization, next_keyword,
                            set_status, upsert_keyword)

    s = get_session()
    site = _site(s)
    a = upsert_keyword(s, site.id, "best crm for agencies", intent="commercial",
                       volume=1000, difficulty=20.0, winnability=0.6)
    b = upsert_keyword(s, site.id, "what is a crm", intent="informational",
                       volume=5000, difficulty=50.0, winnability=0.5)
    assert a.priority_score > 0
    # nothing briefable until approved/queued
    assert briefable_rows(s, site.id) == []
    set_status(s, a.id, "approved")
    set_status(s, b.id, "queued")
    nxt = next_keyword(s, site.id)
    assert nxt is not None and nxt.keyword == "best crm for agencies"
    # cannibalization guard flags near-duplicate
    verdict = check_cannibalization(s, site.id, "best crm for agencies pricing")
    assert verdict["overlap"] is True
    s.close()


def test_seo_provider_off_is_manual():
    from lib.db import get_session
    from lib.seo_provider import get_keyword_data

    s = get_session()
    data = get_keyword_data(s, "best crm", manual={"volume": 123, "difficulty": 11,
                                                  "intent": "commercial"})
    assert data["provider"] == "off"
    assert data["volume"] == 123
    s.close()


def test_brand_dna_inject():
    from lib.brand_dna import inject_into_system_prompt, load_profile, save_profile
    from lib.db import get_session

    s = get_session()
    site = _site(s, slug="brand")
    save_profile(s, site.id, {"pov": "first", "banned_phrases": ["synergy"]})
    profile = load_profile(s, site.id)
    out = inject_into_system_prompt("Write the brief.", profile)
    assert "BRAND DNA" in out and "synergy" in out
    s.close()


def test_factcheck_gate_blocks_unsourced():
    from lib.factcheck import gate_factcheck

    md = "Nespresso brews in 30 seconds and saves 40% of time."
    result = gate_factcheck(md, source_excerpts=["Nespresso brews in 30 seconds per review"])
    assert result["claim_count"] >= 1
    assert result["pass"] is False  # 40% claim has no source


def test_eval_gate_subscore_floor():
    from lib.eval_gate import EvalReport, check_gate

    good = EvalReport(overall=95, sub_scores={k: 85 for k in
                      ("accuracy", "depth", "seo", "voice", "originality", "citability")},
                      guidance=[{"observation": "o", "fail_check": "f", "leading_indicator": "l"}])
    assert check_gate(good)["publish"] is True
    bad = EvalReport(overall=95, sub_scores={k: 85 for k in
                     ("accuracy", "depth", "seo", "voice", "originality", "citability")})
    bad.sub_scores["voice"] = 70
    verdict = check_gate(bad)
    assert verdict["publish"] is False
    assert any("voice" in r for r in verdict["reasons"])


def test_geo_helpers():
    from lib.geo import (article_schema, faq_schema, generate_llms_txt,
                         markdown_alternate, next_available_slug, tldr_block)

    assert "TL;DR" in tldr_block(" ".join(["word"] * 50))
    assert next_available_slug("Hello World", {"hello-world"}) == "hello-world-2"
    assert faq_schema([{"question": "Q?", "answer": "A."}])["@type"] == "FAQPage"
    assert article_schema("T", "https://x/y")["@type"] == "Article"
    assert "Key pages" in generate_llms_txt("Acme", "https://acme.test",
                                            [{"title": "Home", "url": "https://acme.test/"}])
    assert "# T" in markdown_alternate("T", "body text")


def test_cost_ledger_totals():
    from lib.cost_ledger import article_total, record_cost
    from lib.db import Article, get_session

    s = get_session()
    site = _site(s, slug="costs")
    art = Article(site_id=site.id, title="T")
    s.add(art)
    s.commit()
    s.refresh(art)
    record_cost(s, art.id, "llm", 0.01)
    record_cost(s, art.id, "image", 0.02)
    record_cost(s, art.id, "data", 0.11)
    total = article_total(s, art.id)
    assert total["total_usd"] == pytest.approx(0.14)
    s.close()


def test_wordpress_prepublish_block(monkeypatch):
    from lib.wordpress import PreparedPost, WPConfig, WordPressConnector

    cfg = WPConfig(base_url="https://example.com", username="u", app_password="p")
    conn = WordPressConnector.__new__(WordPressConnector)
    conn.cfg = cfg
    monkeypatch.setattr(WordPressConnector, "existing_slugs", lambda self: {"my-post"})
    from lib.wordpress import PreparedPost as P

    post = P(title="My Post", html="<p>hi</p>", markdown="hi [x](https://example.com)",
             slug="my-post")
    checks = WordPressConnector.pre_publish_checks(conn, post)
    assert checks["slug"] == "my-post-2"
    assert checks["duplicate"] is True


def test_sdk_routes():
    from fastapi.testclient import TestClient

    from sdk.server import router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    created = client.post("/sdk/v1/articles", json={"site_slug": "sdk-site", "keyword": "k"})
    assert created.status_code == 200
    article_id = created.json()["id"]
    got = client.get(f"/sdk/v1/articles/{article_id}")
    assert got.status_code == 200
    content = client.get(f"/sdk/v1/articles/{article_id}/content")
    assert content.status_code == 200 and "html" in content.json()
