"""§5.11/§5.13 Elementor render target — builder (pure), render switch,
connector fail-open, service ops, REST routes, MCP tools."""
import json

import pytest


# ---------------------------------------------------------------------------
# Fixture: isolated DB + clean env (pattern from tests/test_api_mcp.py)
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch):
    import os

    workdir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           ".test-tmp-phase1")
    os.makedirs(workdir, exist_ok=True)
    db_file = os.path.join(workdir, "elementor.db")
    try:
        os.remove(db_file)
    except OSError:
        pass
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.delenv("SDK_MASTER_KEY", raising=False)
    monkeypatch.delenv("WP_BASE_URL", raising=False)
    monkeypatch.delenv("WP_USERNAME", raising=False)
    monkeypatch.delenv("WP_APP_PASSWORD", raising=False)
    monkeypatch.delenv("WP_RENDER_TARGET", raising=False)
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


# ---------------------------------------------------------------------------
# Builder (pure)
# ---------------------------------------------------------------------------
def test_build_blog_page_data_structure():
    from lib.elementor import build_blog_page_data

    data = build_blog_page_data("Post Title", "<p>Body</p>")
    assert len(data) == 1
    root = data[0]
    assert root["elType"] == "container" and root["isInner"] is False
    assert len(root["elements"]) == 2
    heading, html_widget = root["elements"]
    assert heading["widgetType"] == "heading"
    assert heading["settings"]["title"] == "Post Title"
    assert heading["settings"]["header_size"] == "h1"
    assert html_widget["widgetType"] == "html"
    assert html_widget["settings"]["html"] == "<p>Body</p>"
    # 7-char hex ids, unique, like the Elementor editor generates
    ids = [root["id"], heading["id"], html_widget["id"]]
    assert all(len(i) == 7 and all(c in "0123456789abcdef" for c in i) for i in ids)
    assert len(set(ids)) == 3
    # idempotent per call is NOT expected — but structure must be stable
    again = build_blog_page_data("Post Title", "<p>Body</p>", header_size="h2")
    assert again[0]["elements"][0]["settings"]["header_size"] == "h2"


def test_elementor_meta_serializes_array():
    from lib.elementor import build_blog_page_data, elementor_meta

    elements = build_blog_page_data("T", "<p>b</p>")
    meta = elementor_meta(elements, page_settings={"hide_title": "yes"})
    # _elementor_data is a STRING containing the plain array (schema type: string)
    assert isinstance(meta["_elementor_data"], str)
    assert json.loads(meta["_elementor_data"]) == elements
    assert meta["_elementor_edit_mode"] == "builder"
    assert meta["_elementor_template_type"] == "wp-post"
    assert meta["_elementor_page_settings"] == {"hide_title": "yes"}
    # page_settings omitted → key absent (partial update must not clobber)
    meta2 = elementor_meta(elements)
    assert "_elementor_page_settings" not in meta2


# ---------------------------------------------------------------------------
# Render target switch
# ---------------------------------------------------------------------------
def test_resolve_render_target_env_and_override():
    import os

    from lib.wordpress import _resolve_render_target

    assert _resolve_render_target() == "blocks"  # default
    os.environ["WP_RENDER_TARGET"] = "elementor"
    assert _resolve_render_target() == "elementor"
    assert _resolve_render_target("blocks") == "blocks"  # explicit beats env
    os.environ["WP_RENDER_TARGET"] = "gutenberg-typo"
    assert _resolve_render_target() == "blocks"  # unknown → blocks (fail-safe)


def test_build_prepared_post_elementor_plain_html():
    from lib.wordpress import build_prepared_post

    post = build_prepared_post(
        title="My Post", markdown="# Body\n\nText.",
        faqs=[{"question": "Q?", "answer": "A."}],
        cta={"label": "Go", "url": "https://x.com/go", "text": "CTA"},
        render_target="elementor",
    )
    assert post.render_target == "elementor"
    assert "<!-- wp:" not in post.html  # plain HTML for the Elementor html widget
    assert "<h1>Body</h1>" in post.html
    # FAQ stays OUT of the html widget — it becomes a native accordion widget
    assert "faq-block" not in post.html and "<details" not in post.html
    assert post.faqs == [{"question": "Q?", "answer": "A."}]
    assert 'class="cta-block"' in post.html
    assert post.faq_schema["@type"] == "FAQPage"


def test_build_blog_page_data_faq_accordion_widget():
    from lib.elementor import build_blog_page_data

    data = build_blog_page_data("T", "<p>b</p>", faqs=[
        {"question": "Q1?", "answer": "A1"},
        {"question": "   ", "answer": "dropped"},
        {"question": "Q2?", "answer": "<p>already html</p>"},
    ])
    els = data[0]["elements"]
    assert len(els) == 4  # heading, html, FAQ heading, accordion
    faq_heading, accordion = els[2], els[3]
    assert faq_heading["widgetType"] == "heading"
    assert faq_heading["settings"]["header_size"] == "h2"
    assert accordion["widgetType"] == "accordion"
    tabs = accordion["settings"]["tabs"]
    assert len(tabs) == 2  # blank question dropped
    assert tabs[0]["tab_title"] == "Q1?"
    assert tabs[0]["tab_content"] == "<p>A1</p>"  # plain text wrapped
    assert tabs[1]["tab_content"] == "<p>already html</p>"  # html kept
    assert all(len(t["_id"]) == 7 for t in tabs)
    # no faqs → exactly the two baseline widgets
    base = build_blog_page_data("T", "<p>b</p>")
    assert [e["widgetType"] for e in base[0]["elements"]] == ["heading", "html"]


def test_build_prepared_post_default_stays_blocks():
    from lib.wordpress import build_prepared_post

    post = build_prepared_post(title="T", markdown="# Body\n\nText.")
    assert post.render_target == "blocks"
    assert "<!-- wp:heading" in post.html


# ---------------------------------------------------------------------------
# Connector: publish() elementor branch (create-then-write, fail-open)
# ---------------------------------------------------------------------------
class _Resp:
    def __init__(self, j):
        self._j = j

    def raise_for_status(self):
        pass

    def json(self):
        return self._j


def _connector_with_fake_session(monkeypatch):
    from lib.wordpress import WPConfig, WordPressConnector

    conn = WordPressConnector(WPConfig(base_url="https://x", username="u", app_password="p"))
    recorded = {"posts": 0, "payload": None}

    class FakeSession:
        headers = {}

        def post(self, url, json=None, **k):
            recorded["posts"] += 1
            recorded["payload"] = json
            return _Resp({"id": 7, "link": "https://x/7"})

        def get(self, url, **k):
            return _Resp([])

    conn.session = FakeSession()
    conn.pre_publish_checks = lambda post: {
        "slug": "my-post", "duplicate": False, "has_invalid_links": False, "invalid": [],
    }
    conn._ensure_term = lambda kind, name: 1
    return conn, recorded


class _FakeElementorClient:
    """Stands in for lib.elementor.ElementorClient (patched module-wide)."""
    saved: list = []
    fail: bool = False

    def __init__(self, cfg):
        self.cfg = cfg

    def available(self):
        return {"available": True, "meta_keys": ["_elementor_data"], "hint": ""}

    def get_document(self, post_id, post_type="posts"):
        return {"id": post_id, "url": f"https://x/{post_id}", "status": "publish",
                "is_elementor": True, "elements": [], "element_count": 0,
                "page_settings": {}, "edit_mode": "builder",
                "template_type": "wp-post"}

    def save_document(self, post_id, elements, **kw):
        if _FakeElementorClient.fail:
            raise RuntimeError("elementor meta rejected")
        _FakeElementorClient.saved.append({"post_id": post_id, "elements": elements, **kw})
        return {"ok": True, "id": post_id, "url": f"https://x/{post_id}",
                "saved_elements": len(elements), "cache_note": "stale CSS possible"}


@pytest.fixture
def fake_elementor(monkeypatch):
    _FakeElementorClient.saved = []
    _FakeElementorClient.fail = False
    monkeypatch.setattr("lib.elementor.ElementorClient", _FakeElementorClient)
    return _FakeElementorClient


def test_publish_elementor_writes_document_after_post(monkeypatch, fake_elementor):
    from lib.wordpress import build_prepared_post

    conn, recorded = _connector_with_fake_session(monkeypatch)
    post = build_prepared_post(title="My Post", markdown="# H\n\ntext",
                               render_target="elementor")
    result = conn.publish(post, mode="draft")

    # body saved as plain HTML (no Gutenberg comments) — valid fallback post
    assert "<!-- wp:" not in recorded["payload"]["content"]
    # exactly ONE post create → an elementor failure can never duplicate
    assert recorded["posts"] == 1
    assert result["elementor"]["ok"] is True
    # document written onto the created post, heading carries the H1,
    # page settings hide the WP title
    saved = fake_elementor.saved[0]
    assert saved["post_id"] == 7
    assert saved["page_settings"] == {"hide_title": "yes"}
    heading, html_widget = saved["elements"][0]["elements"]
    assert heading["settings"]["title"] == "My Post"
    assert '<h1>H</h1>' in html_widget["settings"]["html"]


def test_publish_elementor_faq_goes_to_widget_not_html(monkeypatch, fake_elementor):
    from lib.wordpress import build_prepared_post

    conn, recorded = _connector_with_fake_session(monkeypatch)
    post = build_prepared_post(title="My Post", markdown="# H\n\ntext",
                               faqs=[{"question": "Q?", "answer": "A."}],
                               render_target="elementor")
    conn.publish(post, mode="draft")

    # fallback post content keeps a plain-<details> FAQ section (no blocks)
    assert "<details" in recorded["payload"]["content"]
    assert "<!-- wp:" not in recorded["payload"]["content"]
    # html widget is FAQ-free; a native accordion widget carries the FAQ
    saved = fake_elementor.saved[0]
    heading, html_widget, faq_heading, accordion = saved["elements"][0]["elements"]
    assert "<details" not in html_widget["settings"]["html"]
    assert accordion["widgetType"] == "accordion"
    assert accordion["settings"]["tabs"][0]["tab_title"] == "Q?"


def test_publish_elementor_fails_open(monkeypatch, fake_elementor):
    from lib.wordpress import build_prepared_post

    fake_elementor.fail = True
    conn, recorded = _connector_with_fake_session(monkeypatch)
    post = build_prepared_post(title="My Post", markdown="# H\n\ntext",
                               render_target="elementor")
    result = conn.publish(post, mode="draft")  # must NOT raise

    assert recorded["posts"] == 1  # post created exactly once
    assert result["elementor"]["ok"] is False
    assert "RuntimeError" in result["elementor"]["error"]
    assert "Gutenberg" in result["elementor"]["fallback"]


def test_publish_blocks_target_has_no_elementor_key(monkeypatch):
    from lib.wordpress import build_prepared_post

    conn, recorded = _connector_with_fake_session(monkeypatch)
    post = build_prepared_post(title="My Post", markdown="# H\n\ntext")  # blocks default
    result = conn.publish(post)
    assert "elementor" not in result
    assert "<!-- wp:" in recorded["payload"]["content"]


# ---------------------------------------------------------------------------
# Service ops
# ---------------------------------------------------------------------------
def test_elementor_available_requires_wp_config():
    from sdk import service

    out = service.elementor_available()
    assert "error" in out and "WP_BASE_URL" in out["error"]
    assert out["next"]  # actionable


def test_elementor_document_validates_post_type():
    from sdk import service

    out = service.elementor_document(1, post_type="posts; drop")
    assert "error" in out and "post_type" in out["error"]


def test_elementor_save_validates_elements_and_audits(monkeypatch, fake_elementor):
    from sdk import service
    from lib.db import AuditLog, get_session

    monkeypatch.setenv("WP_BASE_URL", "https://x")
    monkeypatch.setenv("WP_USERNAME", "u")
    monkeypatch.setenv("WP_APP_PASSWORD", "p")

    assert "error" in service.elementor_save(5, [])
    assert "error" in service.elementor_save(5, "not-a-list")

    ok = service.elementor_save(5, [{"id": "abc1234", "elType": "container",
                                     "settings": {}, "elements": []}])
    assert ok["ok"] is True and ok["post_id"] == 5

    s = get_session()
    try:
        row = s.query(AuditLog).filter(AuditLog.action == "elementor.save").one()
        assert row.payload["post_id"] == 5
        assert row.payload["elements"] == 1
    finally:
        s.close()


def test_elementor_build_requires_article_content():
    from sdk import service

    site = service.upsert_site("el-site")
    art = service.submit_article("el-site", keyword="kw")
    out = service.elementor_build(art["id"])
    assert "error" in out and "no content" in out["error"]
    assert "not found" in service.elementor_build(99999)["error"]


def test_elementor_build_creates_post_and_stores_id(monkeypatch, fake_elementor):
    import lib.db as db
    from sdk import service

    monkeypatch.setenv("WP_BASE_URL", "https://x")
    monkeypatch.setenv("WP_USERNAME", "u")
    monkeypatch.setenv("WP_APP_PASSWORD", "p")

    created = {"count": 0}

    class FakeConnector:
        def __init__(self, cfg):
            pass

        def publish(self, post, mode="draft"):
            created["count"] += 1
            assert post.render_target == "elementor"
            assert "<!-- wp:" not in post.html
            return {"id": 42, "url": "https://x/42", "slug": post.slug,
                    "status": "draft",
                    "elementor": {"ok": True, "id": 42, "saved_elements": 2}}

    monkeypatch.setattr("lib.wordpress.WordPressConnector", FakeConnector)

    site = service.upsert_site("el-site2")
    art = service.submit_article("el-site2", keyword="elementor kw")
    s = db.get_session()
    try:
        row = s.get(db.Article, art["id"])
        row.content_md = "# Title\n\nBody text."
        row.meta = {**(row.meta or {}), "summary": "desc"}
        s.commit()
    finally:
        s.close()

    out = service.elementor_build(art["id"])
    assert out["wp_post_id"] == 42
    assert out["render_target"] == "elementor"
    assert out["elementor"]["ok"] is True
    assert created["count"] == 1

    # meta.wp_post_id persisted → a second build must REUSE, not duplicate
    out2 = service.elementor_build(art["id"])
    assert out2["wp_post_id"] == 42
    assert created["count"] == 1  # publish path not taken again

    from lib.db import AuditLog, get_session

    g = get_session()
    try:
        rows = g.query(AuditLog).filter(AuditLog.action == "article.elementor_build").all()
        assert len(rows) == 2  # create-path build + reuse-path save, both audited
        assert rows[0].payload["wp_post_id"] == 42
        assert rows[1].payload["wp_post_id"] == 42
        art_row = g.get(db.Article, art["id"])
        assert art_row.meta["wp_post_id"] == 42
    finally:
        g.close()


def test_elementor_build_saves_onto_existing_post(monkeypatch, fake_elementor):
    import lib.db as db
    from sdk import service

    monkeypatch.setenv("WP_BASE_URL", "https://x")
    monkeypatch.setenv("WP_USERNAME", "u")
    monkeypatch.setenv("WP_APP_PASSWORD", "p")

    site = service.upsert_site("el-site3")
    art = service.submit_article("el-site3", keyword="existing post kw")
    s = db.get_session()
    try:
        row = s.get(db.Article, art["id"])
        row.content_md = "# Title\n\nBody."
        s.commit()
    finally:
        s.close()

    out = service.elementor_build(art["id"], post_id=99)
    assert out["wp_post_id"] == 99
    assert out["elementor"]["ok"] is True
    saved = fake_elementor.saved[0]
    assert saved["post_id"] == 99
    assert saved["page_settings"] == {"hide_title": "yes"}


# ---------------------------------------------------------------------------
# REST routes (thin over service — patch the service, assert wiring)
# ---------------------------------------------------------------------------
def test_rest_elementor_routes(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import sdk.service as svc
    from sdk.server import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    # probe: always 200 — body carries status or error+next
    monkeypatch.setattr(svc, "elementor_available",
                        lambda: {"available": False, "meta_keys": [], "hint": "old elementor"})
    got = client.get("/sdk/v1/elementor/available")
    assert got.status_code == 200 and got.json()["available"] is False

    monkeypatch.setattr(svc, "elementor_document",
                        lambda post_id, post_type="posts": {"id": post_id, "elements": []})
    doc = client.get("/sdk/v1/elementor/posts/7")
    assert doc.status_code == 200 and doc.json()["id"] == 7

    saved = {}

    def fake_save(post_id, elements, post_type="posts", page_settings=None):
        saved.update(post_id=post_id, n=len(elements), page_settings=page_settings)
        return {"ok": True, "id": post_id}

    monkeypatch.setattr(svc, "elementor_save", fake_save)
    ok = client.post("/sdk/v1/elementor/posts/7",
                     json={"elements": [{"id": "abc1234", "elType": "container"}],
                           "page_settings": {"hide_title": "yes"}})
    assert ok.status_code == 200 and saved["post_id"] == 7 and saved["n"] == 1
    assert saved["page_settings"] == {"hide_title": "yes"}

    monkeypatch.setattr(svc, "elementor_build",
                        lambda article_id, post_id=None, mode="draft":
                        {"article_id": article_id, "wp_post_id": 42,
                         "render_target": "elementor"})
    built = client.post("/sdk/v1/elementor/articles/3/build", json={"mode": "draft"})
    assert built.status_code == 200 and built.json()["wp_post_id"] == 42
    # validation-style service errors → 400; missing article/content → 404
    monkeypatch.setattr(svc, "elementor_build",
                        lambda article_id, post_id=None, mode="draft":
                        {"error": "invalid mode 'x'"})
    assert client.post("/sdk/v1/elementor/articles/3/build",
                       json={}).status_code == 400
    monkeypatch.setattr(svc, "elementor_build",
                        lambda article_id, post_id=None, mode="draft":
                        {"error": "article 3 not found"})
    assert client.post("/sdk/v1/elementor/articles/3/build",
                       json={}).status_code == 404


# ---------------------------------------------------------------------------
# MCP tools (JSON-string inputs parsed at the tool edge)
# ---------------------------------------------------------------------------
def test_mcp_elementor_tools_call_service(monkeypatch, fake_elementor):
    import asyncio

    import sdk.service as svc
    from mcp_server.server import mcp

    monkeypatch.setenv("WP_BASE_URL", "https://x")
    monkeypatch.setenv("WP_USERNAME", "u")
    monkeypatch.setenv("WP_APP_PASSWORD", "p")

    async def run():
        avail = await mcp._tool_manager.call_tool("contentfte_elementor_available", {})
        doc = await mcp._tool_manager.call_tool(
            "contentfte_elementor_document",
            {"params": {"post_id": 7, "post_type": "posts"}})
        # invalid JSON string → error dict, never raises
        bad = await mcp._tool_manager.call_tool(
            "contentfte_elementor_save",
            {"params": {"post_id": 7, "elements_json": "{not json"}})
        # valid JSON array string → parsed list reaches the service
        ok = await mcp._tool_manager.call_tool(
            "contentfte_elementor_save",
            {"params": {"post_id": 7,
                        "elements_json": '[{"id":"abc1234","elType":"container",'
                                         '"settings":{},"elements":[]}]',
                        "page_settings_json": '{"hide_title":"yes"}'}})
        return (json.loads(avail), json.loads(doc), json.loads(bad), json.loads(ok))

    avail, doc, bad, ok = asyncio.run(run())
    assert avail["available"] is True
    assert doc["id"] == 7
    assert "error" in bad and "not valid JSON" in bad["error"]
    assert ok["ok"] is True and ok["post_id"] == 7

    # elements_json that decodes to an object (not array) → error
    async def non_array():
        return json.loads(await mcp._tool_manager.call_tool(
            "contentfte_elementor_save",
            {"params": {"post_id": 7, "elements_json": '{"id":"x"}'}}))

    out = asyncio.run(non_array())
    assert "array" in out["error"]


def test_mcp_elementor_build_uses_service(monkeypatch):
    import asyncio

    import sdk.service as svc
    from mcp_server.server import mcp

    monkeypatch.setattr(svc, "elementor_build",
                        lambda article_id, post_id=None, mode="draft":
                        {"article_id": article_id, "wp_post_id": 42,
                         "render_target": "elementor", "elementor": {"ok": True}})
    out = json.loads(asyncio.run(mcp._tool_manager.call_tool(
        "contentfte_elementor_build",
        {"params": {"article_id": 3, "mode": "draft"}})))
    assert out["article_id"] == 3 and out["wp_post_id"] == 42
