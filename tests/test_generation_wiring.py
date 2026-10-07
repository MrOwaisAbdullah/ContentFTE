"""Real generation behind generate_article (TASKS: brief -> generate ->
status -> publish end-to-end). Everything runs with an injected generate_fn
or a monkeypatched service._default_generate — never the network in CI."""
import asyncio
import json

import pytest


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch):
    import os

    workdir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           ".test-tmp-phase1")
    os.makedirs(workdir, exist_ok=True)
    db_file = os.path.join(workdir, "generation.db")
    try:
        os.remove(db_file)
    except OSError:
        pass
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.delenv("SDK_MASTER_KEY", raising=False)
    monkeypatch.delenv("WP_BASE_URL", raising=False)
    monkeypatch.delenv("WP_USERNAME", raising=False)
    monkeypatch.delenv("WP_APP_PASSWORD", raising=False)
    import lib.db as db

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


_BODY = ("## What is a CRM for agencies?\n\n"
         + "A CRM tracks client pipelines and follow-ups. " * 12
         + "\n\n## FAQs\n\n**Which CRM is best for agencies?**\n"
         + "It depends on team size and budget.\n\n"
         + "**How much does a CRM cost?**\nPlans start near $30 per seat.\n")

ENVELOPE = {
    "status": "success",
    "Title": "Best CRM for Agencies in 2026",
    "Generated Content": "> **TL;DR** - The best CRM for agencies balances "
                          "pipeline visibility with fast client reporting.\n\n" + _BODY,
    "Summary": "The best CRM for agencies, compared on price, pipeline features, "
               "and reporting speed.",
    "FAQs": json.dumps([
        {"question": "Which CRM is best for agencies?",
         "answer": "It depends on team size and budget."},
        {"question": "How much does a CRM cost?",
         "answer": "Plans start near $30 per seat."},
    ]),
    "Quality Score": "92",
    "Claims Notes": "pricing verified against vendor pages",
    "errors": [],
    "warnings": ["minor: one source was paywalled"],
}


async def _fake_envelope(brief: dict) -> dict:
    assert brief.get("keyword"), "brief must carry the keyword"
    assert brief.get("brief_markdown"), "brief must carry composed markdown"
    return dict(ENVELOPE)


def test_generate_content_persists_envelope_to_drafted():
    from sqlalchemy import select

    from lib.db import Article, AuditLog, KeywordLedger, get_session
    from sdk import service

    art = service.submit_article("gen-site", keyword="best crm for agencies")
    out = asyncio.run(service.generate_content(art["id"], generate_fn=_fake_envelope))
    assert out["status"] == "drafted" and out["event"] == "article.drafted"
    assert out["title"] == "Best CRM for Agencies in 2026"
    assert out["quality_score"] == 92.0 and out["words"] > 50

    s = get_session()
    try:
        row = s.get(Article, art["id"])
        assert row.status == "drafted"
        assert row.content_md.startswith("> **TL;DR**")
        assert row.title == "Best CRM for Agencies in 2026"
        assert row.meta["summary"].startswith("The best CRM")
        assert row.meta["faqs"][0]["question"] == "Which CRM is best for agencies?"
        assert row.meta["generation"]["quality_score"] == 92.0
        assert row.meta["generation"]["regenerated"] is False
        assert any("minor: one source" in w
                   for w in row.meta["generation"]["warnings"])
        assert row.scores["overall"] == 92.0
        # ledger advanced to drafted (§5.16 lifecycle)
        led = s.get(KeywordLedger, row.keyword_id)
        assert led is not None and led.status == "drafted"
        # audit row
        audited = s.execute(
            select(AuditLog).where(AuditLog.article_id == art["id"],
                                   AuditLog.action == "article.generate")
        ).scalars().first()
        assert audited is not None
        assert audited.payload["event"] == "article.drafted"
        assert audited.payload["words"] == out["words"]
    finally:
        s.close()


def test_generate_is_idempotent_without_regenerate():
    from sqlalchemy import func, select

    from lib.db import AuditLog, get_session
    from sdk import service

    art = service.submit_article("gen-site", keyword="idempotent kw")
    first = asyncio.run(service.generate_content(art["id"], generate_fn=_fake_envelope))
    assert first.get("deduplicated") is None
    second = asyncio.run(service.generate_content(art["id"], generate_fn=_fake_envelope))
    assert second["deduplicated"] is True and second["has_content"] is True
    assert second["status"] == "drafted"

    s = get_session()
    try:
        count = s.execute(select(func.count(AuditLog.id)).where(
            AuditLog.article_id == art["id"],
            AuditLog.action == "article.generate")).scalar()
        assert count == 1  # second call wrote nothing
    finally:
        s.close()


def test_regenerate_approved_article_reverts_to_drafted():
    from lib.db import Article, get_session
    from sdk import service

    art = service.submit_article("gen-site", keyword="rewrite kw")
    asyncio.run(service.generate_content(art["id"], generate_fn=_fake_envelope))
    assert service.approve_article(art["id"], True)["status"] == "approved"

    async def updated(brief):
        env = dict(ENVELOPE)
        env["Title"] = "Rewritten Title"
        env["Generated Content"] = "## Fresh section\n\n" + "New copy. " * 40
        return env

    out = asyncio.run(service.generate_content(art["id"], generate_fn=updated,
                                               regenerate=True))
    assert out["status"] == "drafted" and out["title"] == "Rewritten Title"
    s = get_session()
    try:
        row = s.get(Article, art["id"])
        assert row.status == "drafted"          # approval does not survive a rewrite
        assert "Fresh section" in row.content_md
        assert row.meta["generation"]["regenerated"] is True
    finally:
        s.close()


def test_generate_unknown_article_returns_error():
    from sdk import service

    out = asyncio.run(service.generate_content(9999, generate_fn=_fake_envelope))
    assert out["error"] and "not found" in out["error"]
    assert out["next"]


def test_generate_envelope_error_status_leaves_row_briefed():
    from lib.db import Article, get_session
    from sdk import service

    art = service.submit_article("gen-site", keyword="failing kw")

    async def failing(brief):
        return {"status": "error",
                "message": "No ungenerated briefs found in content_briefs.",
                "errors": ["empty queue"], "warnings": []}

    out = asyncio.run(service.generate_content(art["id"], generate_fn=failing))
    assert "No ungenerated briefs" in out["error"]
    assert out["next"]
    s = get_session()
    try:
        row = s.get(Article, art["id"])
        assert row.status == "briefed" and not row.content_md
    finally:
        s.close()


def test_generate_runner_exception_fails_open():
    from lib.db import Article, get_session
    from sdk import service

    art = service.submit_article("gen-site", keyword="exploding kw")

    async def boom(brief):
        raise RuntimeError("provider quota exceeded")

    out = asyncio.run(service.generate_content(art["id"], generate_fn=boom))
    assert out["error"].startswith("generation failed")
    assert "quota exceeded" in out["error"]
    assert "LLM keys" in out["next"]
    s = get_session()
    try:
        row = s.get(Article, art["id"])
        assert row.status == "briefed" and not row.content_md
    finally:
        s.close()


def test_generate_salvages_raw_markdown_output():
    from lib.db import Article, get_session
    from sdk import service

    art = service.submit_article("gen-site", keyword="markdown kw")
    raw = ("# Salvaged Post Title\n\n"
           + "This fallback model skipped the JSON envelope entirely but still "
           + "wrote a complete, well-researched post body with enough substance "
           + "for the salvage path to recover it from raw markdown text. " * 3
           + "\n\n**Summary**: A salvaged summary under 160 characters.\n\n"
           + "## FAQs\n\n**What is salvage?**\nRecovering output the model "
           + "returned in the wrong shape.\n")

    out = asyncio.run(service.generate_content(
        art["id"], generate_fn=lambda b: asyncio.sleep(0, raw)))
    assert out["status"] == "drafted"
    s = get_session()
    try:
        row = s.get(Article, art["id"])
        assert row.title == "Salvaged Post Title"
        assert "salvage path" in row.content_md
        assert row.meta["summary"] == "A salvaged summary under 160 characters."
        assert row.meta["faqs"][0]["question"] == "What is salvage?"
    finally:
        s.close()


def test_parse_generation_output_variants():
    from lib.generation import get_field, parse_generation_output

    # dict passthrough
    assert parse_generation_output({"Title": "x"}) == {"Title": "x"}
    # plain JSON envelope
    assert parse_generation_output('{"status": "success", "Title": "T"}')["Title"] == "T"
    # fenced envelope with raw newlines inside values (confirmed-live shape)
    fenced = '```json\n{"status": "success", "Generated Content": "line1\nline2"}\n```'
    assert "line1" in parse_generation_output(fenced)["Generated Content"]
    # wrapper nesting: field one level deep (lenient via get_field)
    wrapped = json.dumps({"status": "success",
                          "data": {"Generated Content": "nested body " * 30}})
    parsed = parse_generation_output(wrapped)
    assert "nested body" in str(get_field(parsed, "Generated Content"))
    # garbage / too-short markdown -> None
    assert parse_generation_output("sorry, I cannot do that") is None
    assert parse_generation_output("# Tiny\n\nshort") is None
    assert parse_generation_output("") is None
    assert parse_generation_output(None) is None


def test_build_brief_payload_uses_template_and_submitted_brief():
    from lib.generation import build_brief_payload, render_prompt

    payload = build_brief_payload(
        keyword="best crm for agencies", intent="commercial",
        brief_meta={"description": "Compare CRMs for agency pipelines.",
                    "faqs": '[{"question": "Q1?", "answer": "A1."}]',
                    "sources": ["https://example.com/crm-study"]},
        research_snapshot="Top results miss pricing transparency.",
        volume=2400, difficulty=41)
    assert payload["keyword"] == "best crm for agencies"
    assert "# best crm for agencies" in payload["brief_markdown"]
    assert "Compare CRMs" in payload["brief_markdown"]
    assert "Commercial investigation" in payload["brief_markdown"]  # §5.16 template
    assert "Search volume: 2400" in payload["brief_markdown"]
    assert payload["faqs"][0]["question"] == "Q1?"
    assert payload["sources"] == ["https://example.com/crm-study"]

    prompt = render_prompt(payload)
    assert "Do NOT call" in prompt and "content_briefs" in prompt
    assert "Generated Content" in prompt
    assert "best crm for agencies" in prompt


def test_rest_generate_route_and_full_status_flow():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from sdk import service
    from sdk.server import router

    async def fake_generate(brief):
        return dict(ENVELOPE)

    prev = service._default_generate
    service._default_generate = fake_generate
    try:
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        aid = client.post("/sdk/v1/articles",
                          json={"site_slug": "rest-gen",
                                "keyword": "rest generate kw"}).json()["id"]
        gen = client.post(f"/sdk/v1/articles/{aid}/generate")
        assert gen.status_code == 200, gen.text
        assert gen.json()["status"] == "drafted"

        # idempotent second POST (no regenerate) stays 200 + drafted
        again = client.post(f"/sdk/v1/articles/{aid}/generate")
        assert again.status_code == 200 and again.json()["deduplicated"] is True

        # unknown article -> 404, failure path -> 502
        assert client.post("/sdk/v1/articles/424242/generate").status_code == 404

        async def failing(brief):
            raise RuntimeError("no providers available")

        service._default_generate = failing
        bad = client.post(f"/sdk/v1/articles/{aid}/generate", json={"regenerate": True})
        assert bad.status_code == 502

        # approve -> publish still works on the drafted article
        service._default_generate = fake_generate
        assert client.post(f"/sdk/v1/articles/{aid}/approve",
                           json={"approved": True}).json()["status"] == "approved"
        pub = client.post(f"/sdk/v1/articles/{aid}/publish", json={"mode": "draft"})
        assert pub.status_code == 200 and pub.json()["status"] == "published"
    finally:
        service._default_generate = prev


def test_mcp_brief_generate_status_publish_end_to_end():
    """The TASKS acceptance chain over MCP: get_brief -> generate_article ->
    get_article_status -> publish (approve gates in between via SDK/REST)."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import lib.db as db
    from lib.ledger import set_status, upsert_keyword
    from mcp_server.server import mcp
    from sdk import service
    from sdk.server import router

    async def fake_generate(brief):
        return dict(ENVELOPE)

    prev = service._default_generate
    service._default_generate = fake_generate
    try:
        # §5.16: briefs pull only approved/queued ledger rows
        site = service.upsert_site("mcp-flow", name="MCP Flow")
        s = db.get_session()
        try:
            row = upsert_keyword(s, site["id"], "mcp end to end kw")
            set_status(s, row.id, "approved")
        finally:
            s.close()

        async def run():
            brief_raw = await mcp._tool_manager.call_tool(
                "contentfte_get_brief", {"params": {"site_slug": "mcp-flow"}})
            gen_raw = await mcp._tool_manager.call_tool(
                "contentfte_generate_article",
                {"params": {"site_slug": "mcp-flow", "keyword": "mcp end to end kw"}})
            status_raw = await mcp._tool_manager.call_tool(
                "contentfte_get_article_status",
                {"params": {"article_id": json.loads(gen_raw)["id"]}})
            return (json.loads(brief_raw), json.loads(gen_raw),
                    json.loads(status_raw))

        brief, generated, status = asyncio.run(run())
        assert brief["keyword"] == "mcp end to end kw"
        assert generated["status"] == "drafted" and generated["event"] == "article.drafted"
        assert status["status"] == "drafted" and status["scores"]["overall"] == 92.0

        # approve happens off-MCP (no approve tool by spec) -> publish via MCP
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)
        assert client.post(f"/sdk/v1/articles/{generated['id']}/approve",
                           json={"approved": True}).json()["status"] == "approved"
        pub_raw = asyncio.run(mcp._tool_manager.call_tool(
            "contentfte_publish_article",
            {"params": {"article_id": generated["id"], "mode": "draft"}}))
        pub = json.loads(pub_raw)
        assert pub["status"] == "published" and pub["event"] == "article.published"
    finally:
        service._default_generate = prev


def test_mcp_generate_tool_deduplicates_and_supports_regenerate():
    from mcp_server.server import mcp
    from sdk import service

    calls = {"n": 0}

    async def counting(brief):
        calls["n"] += 1
        env = dict(ENVELOPE)
        env["Title"] = f"Run {calls['n']}"
        return env

    prev = service._default_generate
    service._default_generate = counting
    try:
        async def run():
            first = json.loads(await mcp._tool_manager.call_tool(
                "contentfte_generate_article",
                {"params": {"site_slug": "dedupe-site", "keyword": "dedupe kw"}}))
            second = json.loads(await mcp._tool_manager.call_tool(
                "contentfte_generate_article",
                {"params": {"site_slug": "dedupe-site", "keyword": "dedupe kw"}}))
            third = json.loads(await mcp._tool_manager.call_tool(
                "contentfte_generate_article",
                {"params": {"site_slug": "dedupe-site", "keyword": "dedupe kw",
                            "regenerate": True}}))
            return first, second, third

        first, second, third = asyncio.run(run())
        assert calls["n"] == 2  # first run + regenerate only
        assert first["title"] == "Run 1" and second["deduplicated"] is True
        assert third["title"] == "Run 2" and third["status"] == "drafted"
    finally:
        service._default_generate = prev
