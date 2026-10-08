"""Phase 1 wiring tests — service layer -> REST API -> MCP (same contract)."""
import json

import pytest


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch):
    import os

    workdir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           ".test-tmp-phase1")
    os.makedirs(workdir, exist_ok=True)
    db_file = os.path.join(workdir, "api.db")
    try:
        os.remove(db_file)
    except OSError:
        pass
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.delenv("SDK_MASTER_KEY", raising=False)
    monkeypatch.delenv("WP_BASE_URL", raising=False)
    import lib.db as db

    # dispose BEFORE deleting — Windows can't unlink a DB file an open
    # pool connection still holds (PermissionError swallowed before).
    if db._engine is not None:
        db._engine.dispose()
    db._engine = None
    db._SessionLocal = None
    try:
        os.remove(db_file)
    except OSError:
        pass
    from sdk import service

    service.init()
    yield
    if db._engine is not None:
        db._engine.dispose()
    try:
        os.remove(db_file)
    except OSError:
        pass


def test_service_full_lifecycle():
    from sdk import service

    assert service.list_sites()["count"] == 0
    site = service.upsert_site("acme", name="Acme", site_type="wordpress")
    assert site["created"] is True

    # brief: empty queue before ledger approval (§5.16)
    assert service.get_brief("acme")["status"] == "empty"

    art = service.submit_article("acme", keyword="best crm for agencies")
    assert art["status"] == "briefed" and art["event"] == "article.ready"
    # idempotent per (site, keyword)
    again = service.submit_article("acme", keyword="best crm for agencies")
    assert again["id"] == art["id"] and again.get("deduplicated") is True

    # publish refused before approval (score gate)
    refused = service.publish_article(art["id"])
    assert "error" in refused and "approved" in refused["error"]

    approved = service.approve_article(art["id"], approved=True, note="gate passed")
    assert approved["status"] == "approved" and approved["event"] == "article.published"

    pub = service.publish_article(art["id"], mode="draft")
    assert pub["status"] == "published" and pub["event"] == "article.published"

    health = service.site_health("acme")
    assert health["site"] == "acme" and "ledger" in health
    assert any("ledger" in c for c in health["checks"])


def test_brief_pulls_only_approved_ledger_rows():
    from lib.db import get_session
    from lib.ledger import set_status, upsert_keyword
    from sdk import service

    site = service.upsert_site("ledger-site")
    s = get_session()
    try:
        row = upsert_keyword(s, site["id"], "how to tie a tie", intent="informational",
                             volume=800, difficulty=10.0)
    finally:
        s.close()
    # researched -> NOT briefable
    assert service.get_brief("ledger-site")["status"] == "empty"
    s = get_session()
    try:
        set_status(s, row.id, "approved")
    finally:
        s.close()
    brief = service.get_brief("ledger-site")
    assert brief["keyword"] == "how to tie a tie"
    assert brief["status"] == "approved" and brief["ledger_id"] == row.id


def test_rest_api_endpoints_and_idempotency():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from sdk.server import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    created = client.post("/sdk/v1/articles",
                          json={"site_slug": "api-site", "keyword": "kw one"},
                          headers={"Idempotency-Key": "abc-123"})
    assert created.status_code == 200
    aid = created.json()["id"]
    # same Idempotency-Key returns cached result without a new row
    cached = client.post("/sdk/v1/articles",
                         json={"site_slug": "api-site", "keyword": "kw one"},
                         headers={"Idempotency-Key": "abc-123"})
    assert cached.json()["id"] == aid

    assert client.get(f"/sdk/v1/articles/{aid}").json()["status"] == "briefed"
    content = client.get(f"/sdk/v1/articles/{aid}/content")
    assert content.status_code == 200 and "html" in content.json()
    ok = client.post(f"/sdk/v1/articles/{aid}/approve", json={"approved": True})
    assert ok.json()["event"] == "article.published"
    health = client.get("/sdk/v1/sites/api-site/health")
    assert health.status_code == 200 and health.json()["site"] == "api-site"
    # 404 for unknown article
    assert client.get("/sdk/v1/articles/99999").status_code == 404


def test_sites_routes_and_publish_gate():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from sdk.server import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    up = client.post("/sdk/v1/sites", json={"slug": "pub-site", "name": "Pub",
                                            "site_type": "custom",
                                            "base_url": "https://pub.example"})
    assert up.status_code == 200
    sites = client.get("/sdk/v1/sites").json()["sites"]
    assert any(s["slug"] == "pub-site" for s in sites)

    aid = client.post("/sdk/v1/articles",
                      json={"site_slug": "pub-site", "keyword": "publish gate"}).json()["id"]
    # publish before approve -> 409 (90/100 + sub-score floor gate)
    blocked = client.post(f"/sdk/v1/articles/{aid}/publish", json={"mode": "draft"})
    assert blocked.status_code == 409
    assert "approved" in blocked.json()["detail"]

    client.post(f"/sdk/v1/articles/{aid}/approve", json={"approved": True})
    pub = client.post(f"/sdk/v1/articles/{aid}/publish", json={"mode": "publish"})
    assert pub.status_code == 200
    assert pub.json()["status"] == "published"
    assert pub.json()["event"] == "article.published"


def test_rest_api_master_key_auth(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from sdk.server import router

    monkeypatch.setenv("SDK_MASTER_KEY", "sekret")
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    denied = client.get("/sdk/v1/sites/x/health", headers={"X-Site-Key": "wrong"})
    assert denied.status_code == 401
    allowed = client.get("/sdk/v1/sites/x/health", headers={"X-Site-Key": "sekret"})
    assert allowed.status_code in (200, 404)  # auth passed; site may not exist


def test_mcp_tools_registered_and_thin_over_service():
    import asyncio

    from mcp_server.server import mcp

    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    expected = {
        "contentfte_list_sites", "contentfte_get_brief",
        "contentfte_list_articles",
        "contentfte_generate_article", "contentfte_get_article_status",
        "contentfte_get_image", "contentfte_publish_article",
        "contentfte_refresh_article",
        "contentfte_stage_images",
        "contentfte_wp_post",
        "contentfte_site_health",
        "contentfte_llms_txt",
        "contentfte_elementor_available", "contentfte_elementor_document",
        "contentfte_elementor_save", "contentfte_elementor_build",
    }
    assert expected == names, f"tool name mismatch: {names ^ expected}"

    # annotations present (skill checklist)
    for t in tools:
        assert t.annotations is not None, t.name


def test_mcp_tool_end_to_end_via_tool_manager(monkeypatch):
    import asyncio

    from mcp_server.server import mcp
    from sdk import service

    # generate_article now runs real generation behind the stub row — inject
    # a fake LLM here so the smoke test stays offline/CI-safe.
    async def fake_generate(brief):
        return {"status": "success", "Title": "MCP KW Post",
                "Generated Content": "## Intro\n\n" + "Body content. " * 40,
                "Summary": "Summary of the mcp kw post for smoke testing.",
                "FAQs": "[]", "Quality Score": "88"}

    monkeypatch.setattr(service, "_default_generate", fake_generate)

    async def run():
        out = await mcp._tool_manager.call_tool(
            "contentfte_generate_article",
            {"params": {"site_slug": "mcp-site", "keyword": "mcp kw"}})
        data = json.loads(out)
        assert data["status"] == "drafted", data
        assert data["event"] == "article.drafted", data
        sites = await mcp._tool_manager.call_tool("contentfte_list_sites", {})
        return json.loads(sites)["count"]

    count = asyncio.run(run())
    assert count == 1


def test_brand_dna_idempotent_injection():
    class FakeAgent:
        def __init__(self, name, instructions):
            self.name = name
            self.instructions = instructions

    from lib.brand_dna import apply_brand_dna

    a = FakeAgent("Brief", "Do briefs.")
    b = FakeAgent("Eval", "Score posts.")
    first = apply_brand_dna([a, b], {"pov": "first", "banned_phrases": ["synergy"]})
    assert first == ["Brief", "Eval"]
    assert a.instructions.startswith("[BRAND DNA")
    assert "synergy" in a.instructions and a.instructions.endswith("Do briefs.")
    # re-run: no double injection
    second = apply_brand_dna([a, b], {"pov": "first"})
    assert second == []
    assert a.instructions.count("[BRAND DNA") == 1


def test_factcheck_tool_gate():
    from tools.factcheck_tool import run_factcheck_gate

    good = run_factcheck_gate(
        draft_markdown="Nespresso brews in 30 seconds.",
        source_excerpts_json=json.dumps(["Nespresso brews in 30 seconds per review"]))
    assert good["pass"] is True and good["claim_count"] >= 1

    bad = run_factcheck_gate(
        draft_markdown="Nespresso saves 40% of time.",
        source_excerpts_json=json.dumps(["Nespresso brews fast"]))
    assert bad["pass"] is False and bad["unverified_count"] >= 1
    assert "Revise FIRST" in bad["guidance"]


def test_content_route_is_unified_delivery_payload():
    """GET /articles/{id}/content == build_delivery_payload + article metadata.

    Single source of truth for custom-site frontends: html is RENDERED from
    markdown at serve time (content_html is never written), plus
    markdown_alternate + Article/FAQ JSON-LD + site-relative url."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import lib.db as db
    from sdk.server import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    client.post("/sdk/v1/sites", json={"slug": "payload-site", "name": "Payload",
                                       "site_type": "custom",
                                       "base_url": "https://payload.example/"})
    aid = client.post("/sdk/v1/articles",
                      json={"site_slug": "payload-site",
                            "keyword": "best crm for agencies"}).json()["id"]

    # simulate the pipeline having written content + meta (sheet mirror shape)
    s = db.get_session()
    try:
        art = s.get(db.Article, aid)
        art.content_md = "# Best CRM for Agencies\n\nBody **bold** with a [link](https://x.example)."
        art.meta = {**(art.meta or {}),
                    "summary": "A meta description.",
                    "faqs": '[{"question": "How much?", "answer": "$20."}]'}
        s.commit()
    finally:
        s.close()

    got = client.get(f"/sdk/v1/articles/{aid}/content")
    assert got.status_code == 200
    body = got.json()

    # rendered html (not the always-empty content_html column)
    assert "<h1>Best CRM for Agencies</h1>" in body["html"]
    assert "<strong>bold</strong>" in body["html"]
    assert body["markdown"].startswith("# Best CRM")
    # .md alternate (§5.8) + schema (Article + FAQ from meta.faqs JSON string)
    assert body["markdown_alternate"].startswith("---")
    assert body["schema"]["article"]["@type"] == "Article"
    assert body["schema"]["faq"]["mainEntity"][0]["name"] == "How much?"
    # slug derived from title (Article.slug stays empty), url = base_url + slug
    assert body["slug"] == "best-crm-for-agencies"
    assert body["url"] == "https://payload.example/best-crm-for-agencies"
    assert body["excerpt"] == "A meta description."
    # article metadata still present (get_images reads meta.images)
    assert body["meta"]["summary"] == "A meta description."
    # FAQ accordion HTML for non-React custom sites (same markup as WP)
    assert "<details" in body["faq_html"] and "contentfte-faq" in body["faq_html"]
    assert body["status"] == "briefed" and body["scores"] == {}


def test_list_articles_route_and_tool():
    """GET /sdk/v1/articles + contentfte_list_articles — the custom-site
    content loader's enumeration entry point (filter by site/status, page)."""
    import asyncio

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import sdk.service as service
    from mcp_server.server import mcp
    from sdk.server import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    service.upsert_site("list-site", site_type="custom")
    a1 = service.submit_article("list-site", keyword="alpha kw")
    a2 = service.submit_article("list-site", keyword="beta kw")
    service.approve_article(a1["id"], approved=True)
    service.publish_article(a1["id"], mode="draft")     # custom → status-only
    service.upsert_site("other-site", site_type="custom")
    a3 = service.submit_article("other-site", keyword="gamma kw")

    # site-scoped + status filter
    got = client.get("/sdk/v1/articles",
                     params={"site_slug": "list-site", "status": "published"})
    assert got.status_code == 200
    body = got.json()
    assert body["total"] == 1 and body["count"] == 1
    row = body["articles"][0]
    assert row["id"] == a1["id"] and row["site_slug"] == "list-site"
    assert row["status"] == "published" and row["created_at"]

    # unscoped lists everything; light fields only (no html/markdown)
    allrows = client.get("/sdk/v1/articles").json()
    assert allrows["total"] == 3
    assert {r["id"] for r in allrows["articles"]} == {a1["id"], a2["id"], a3["id"]}
    assert "markdown" not in allrows["articles"][0]

    # pagination
    page = client.get("/sdk/v1/articles", params={"limit": 1, "offset": 1}).json()
    assert page["total"] == 3 and page["count"] == 1
    assert page["limit"] == 1 and page["offset"] == 1

    # unknown site → service error surfaced as 404
    assert client.get("/sdk/v1/articles", params={"site_slug": "nope"}).status_code == 404

    # MCP tool mirrors the service
    async def run():
        return json.loads(await mcp._tool_manager.call_tool(
            "contentfte_list_articles",
            {"params": {"site_slug": "list-site", "status": "published"}}))

    out = asyncio.run(run())
    assert out["count"] == 1 and out["articles"][0]["id"] == a1["id"]


def test_llms_txt_route_and_tool():
    """GET /sites/{slug}/llms.txt + contentfte_llms_txt — the site-level
    agent index (§5.8 GEO), composed from PUBLISHED articles only."""
    import asyncio

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import sdk.service as service
    from mcp_server.server import mcp
    from sdk.server import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    service.upsert_site("llms-site", name="Acme Roofing", site_type="custom",
                        base_url="https://acme.test")
    a1 = service.submit_article("llms-site", keyword="flatroof repair")
    service.approve_article(a1["id"], approved=True)
    service.publish_article(a1["id"])
    service.submit_article("llms-site", keyword="gutter cleaning")  # stays briefed

    got = client.get("/sdk/v1/sites/llms-site/llms.txt")
    assert got.status_code == 200
    body = got.json()
    assert body["site"] == "llms-site" and body["count"] == 1  # published only
    assert "# Acme Roofing" in body["llms_txt"]
    assert "https://acme.test/flatroof-repair" in body["llms_txt"]

    assert client.get("/sdk/v1/sites/nope/llms.txt").status_code == 404

    async def run():
        return json.loads(await mcp._tool_manager.call_tool(
            "contentfte_llms_txt", {"params": {"site_slug": "llms-site"}}))

    out = asyncio.run(run())
    assert out["count"] == 1 and "# Acme Roofing" in out["llms_txt"]
