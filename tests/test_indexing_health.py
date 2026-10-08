"""§5.6 indexing + sitemap + site_health probes — batch-1 seo-pack gaps.

Covers lib.indexing (IndexNow + Bing WMT, fail-open), lib.geo.sitemap_xml,
the service sitemap/health ops + REST/MCP surfaces, and the publish-path
indexing report. No network: requests.post and health probes are faked.
"""
from __future__ import annotations

import asyncio
import json
import os

import pytest


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch):
    workdir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           ".test-tmp-phase1")
    os.makedirs(workdir, exist_ok=True)
    db_file = os.path.join(workdir, "idx.db")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("SEO_DATA_PROVIDER", "off")
    monkeypatch.delenv("INDEXNOW_KEY", raising=False)
    monkeypatch.delenv("BING_WMT_API_KEY", raising=False)
    monkeypatch.delenv("INDEXING_ENABLED", raising=False)
    import lib.db as db

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


# --- lib.geo.sitemap_xml ------------------------------------------------


def test_sitemap_xml_well_formed():
    from lib.geo import sitemap_xml

    xml = sitemap_xml([
        {"loc": "https://a.test/post-1", "lastmod": "2026-10-08"},
        {"loc": "https://a.test/p?x=1&y=2"},
        {"loc": ""},  # dropped
    ])
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' in xml
    assert "<loc>https://a.test/post-1</loc><lastmod>2026-10-08</lastmod>" in xml
    assert "<loc>https://a.test/p?x=1&amp;y=2</loc>" in xml
    assert xml.count("<url>") == 2
    assert xml.rstrip().endswith("</urlset>")

    empty = sitemap_xml([])
    assert empty.count("<url>") == 0 and "</urlset>" in empty


# --- lib.indexing -------------------------------------------------------


class _Resp:
    def __init__(self, status=200, text=""):
        self.status_code = status
        self.text = text


def test_submit_indexnow_payload_and_statuses(monkeypatch):
    from lib import indexing

    calls = []

    def fake_post(url, **kw):
        calls.append((url, kw))
        return _Resp(202 if "bing.com" in url else 200)

    monkeypatch.setattr(indexing.requests, "post", fake_post)
    rep = indexing.submit_indexnow(
        ["https://site.test/a", "https://site.test/a", "ftp://nope"],
        base_url="https://site.test", key="abc123def456")
    assert rep["ok"] is True and rep["host"] == "site.test" and rep["urls"] == 1
    assert {u for u, _ in calls} == set(indexing.INDEXNOW_ENDPOINTS)
    payload = calls[0][1]["json"]
    assert payload == {
        "host": "site.test",
        "key": "abc123def456",
        "keyLocation": "https://site.test/abc123def456.txt",
        "urlList": ["https://site.test/a"],
    }
    assert calls[0][1]["headers"]["Content-Type"] == \
        "application/json; charset=utf-8"

    # non-accept status -> ok False, body captured
    monkeypatch.setattr(indexing.requests, "post",
                        lambda url, **kw: _Resp(403, "bad key"))
    rep = indexing.submit_indexnow(["https://site.test/a"],
                                   base_url="https://site.test", key="k")
    assert rep["ok"] is False
    assert any(r.get("status") == 403 and "bad key" in r.get("body", "")
               for r in rep["results"])

    # network error -> fail-open per endpoint
    def boom(*a, **k):
        raise ConnectionError("offline")

    monkeypatch.setattr(indexing.requests, "post", boom)
    rep = indexing.submit_indexnow(["https://site.test/a"],
                                   base_url="https://site.test", key="k")
    assert rep["ok"] is False
    assert all("offline" in r.get("error", "") for r in rep["results"])


def test_submit_bing_wmt(monkeypatch):
    from lib import indexing

    seen = {}

    def fake_post(url, **kw):
        seen["url"] = url
        seen.update(kw)
        return _Resp(200, '{"d":null}')

    monkeypatch.setattr(indexing.requests, "post", fake_post)
    rep = indexing.submit_bing_wmt(["https://site.test/a"],
                                   site_url="https://site.test", api_key="K1")
    assert rep["ok"] is True and rep["urls"] == 1
    assert seen["url"].startswith(indexing.BING_WMT_SUBMIT_URL)
    assert "apikey=K1" in seen["url"]
    assert seen["json"] == {"siteUrl": "https://site.test",
                            "urlList": ["https://site.test/a"]}

    monkeypatch.setattr(indexing.requests, "post",
                        lambda url, **kw: _Resp(401, "revoked"))
    rep = indexing.submit_bing_wmt(["https://site.test/a"],
                                   site_url="https://site.test", api_key="K1")
    assert rep["ok"] is False and "revoked" in rep.get("body", "")


def test_submit_published_env_gating(monkeypatch):
    from lib import indexing

    # no keys -> skipped, never calls requests
    def no_calls(*a, **k):
        raise AssertionError("must not hit network without keys")

    monkeypatch.setattr(indexing.requests, "post", no_calls)
    rep = indexing.submit_published("https://site.test/a",
                                    site_url="https://site.test")
    assert rep["skipped"] and "not set" in rep["skipped"]

    # disabled -> skipped
    monkeypatch.setenv("INDEXING_ENABLED", "0")
    monkeypatch.setenv("INDEXNOW_KEY", "abc123")
    rep = indexing.submit_published("https://site.test/a")
    assert rep["skipped"] == "INDEXING_ENABLED=0"
    monkeypatch.delenv("INDEXING_ENABLED")

    # both keys -> both engines called
    calls = []
    monkeypatch.setattr(indexing.requests, "post",
                        lambda url, **kw: calls.append(url) or _Resp(200))
    monkeypatch.setenv("BING_WMT_API_KEY", "BK")
    rep = indexing.submit_published("https://site.test/a",
                                    site_url="https://site.test")
    assert rep["indexnow"]["ok"] is True and rep["bing_wmt"]["ok"] is True
    assert len(calls) == len(indexing.INDEXNOW_ENDPOINTS) + 1

    # invalid url -> skipped
    rep = indexing.submit_published("")
    assert "no live url" in rep.get("skipped", "")


# --- service: publish attaches an indexing report -----------------------


def test_publish_article_attaches_indexing_report():
    from sdk import service

    service.upsert_site("idx-site", name="Idx", site_type="custom",
                        base_url="https://idx.test")
    art = service.submit_article("idx-site", keyword="how to index urls")
    service.approve_article(art["id"], approved=True, note="gate passed")
    pub = service.publish_article(art["id"])
    assert pub["status"] == "published"
    # no keys in the guarded env -> deterministic skipped report (no network)
    assert pub["indexing"]["skipped"] and pub["indexing"]["url"].startswith(
        "https://idx.test/")

    # INDEXING_ENABLED=0 wins over keys
    import lib.indexing as indexing
    orig = indexing.submit_published
    indexing.submit_published = lambda *a, **k: {"skipped": "INDEXING_ENABLED=0"}
    try:
        art2 = service.submit_article("idx-site", keyword="second indexing kw")
        service.approve_article(art2["id"], approved=True, note="ok")
        pub2 = service.publish_article(art2["id"])
        assert pub2["indexing"]["skipped"] == "INDEXING_ENABLED=0"
    finally:
        indexing.submit_published = orig


# --- service: sitemap + REST + MCP --------------------------------------


def test_service_sitemap_xml_published_only():
    from sdk import service

    service.upsert_site("map-site", name="Map Site", site_type="custom",
                        base_url="https://map.test")
    a1 = service.submit_article("map-site", keyword="sitemap protocol guide")
    service.approve_article(a1["id"], approved=True)
    service.publish_article(a1["id"])
    service.submit_article("map-site", keyword="robots txt basics")  # briefed

    out = service.sitemap_xml("map-site")
    assert out["site"] == "map-site" and out["count"] == 1
    assert "<loc>https://map.test/sitemap-protocol-guide</loc>" in out["sitemap_xml"]
    assert "<lastmod>" in out["sitemap_xml"]
    assert 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"' in \
        out["sitemap_xml"]
    assert service.sitemap_xml("nope").get("error")


def test_sitemap_rest_route_and_mcp_tool():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import sdk.service as service
    from mcp_server.server import mcp
    from sdk.server import router

    service.upsert_site("map2-site", name="Map Two", site_type="custom",
                        base_url="https://map2.test")
    a1 = service.submit_article("map2-site", keyword="canonical tags")
    service.approve_article(a1["id"], approved=True)
    service.publish_article(a1["id"])

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    got = client.get("/sdk/v1/sites/map2-site/sitemap.xml")
    assert got.status_code == 200
    body = got.json()
    assert body["count"] == 1 and "<urlset" in body["sitemap_xml"]
    assert client.get("/sdk/v1/sites/nope/sitemap.xml").status_code == 404

    async def run():
        return json.loads(await mcp._tool_manager.call_tool(
            "contentfte_sitemap", {"params": {"site_slug": "map2-site"}}))

    out = asyncio.run(run())
    assert out["count"] == 1 and "<urlset" in out["sitemap_xml"]


# --- site_health probes -------------------------------------------------


def _fake_get(mapping):
    """mapping: url-substring -> (status, json-data)."""

    class Resp:
        def __init__(self, status, data):
            self.status_code = status
            self._data = data

        def json(self):
            return self._data

    def get(url, timeout=None, auth=None, **kw):
        for frag, (status, data) in mapping.items():
            if frag in url:
                return Resp(status, data)
        return Resp(404, {})

    return get


def _ledger_ok(site_dict):
    """Approve one keyword so site_health `ok` isn't gated by an empty queue."""
    from lib.db import get_session
    from lib.ledger import set_status, upsert_keyword

    s = get_session()
    try:
        row = upsert_keyword(s, site_dict["id"], "probe keyword",
                             intent="informational")
        set_status(s, row.id, "approved")
    finally:
        s.close()


def test_site_health_probes_custom_site():
    from sdk import service

    site = service.upsert_site("health-site", name="Health", site_type="custom",
                               base_url="https://health.test")
    _ledger_ok(site)

    fake = _fake_get({"robots.txt": (200, {})})
    out = service.site_health("health-site", http_get=fake)
    assert out["ok"] is True and out["critical"] == []
    assert any(c.startswith("robots.txt: OK") for c in out["checks"])
    assert any("engine-generated" in c for c in out["checks"])
    assert any("base_url" not in c for c in out["checks"])

    # no base_url -> probes skipped, no crash
    service.upsert_site("nourl-site", name="NoURL", site_type="custom")
    out2 = service.site_health("nourl-site")
    assert any("skipped" in c for c in out2["checks"])


def test_site_health_wp_search_visibility(monkeypatch):
    from sdk import service

    monkeypatch.setenv("WP_BASE_URL", "https://wp.test")
    monkeypatch.setenv("WP_USERNAME", "user_admin")
    monkeypatch.setenv("WP_APP_PASSWORD", "pass word")
    site = service.upsert_site("wp-health", name="WP Health",
                               site_type="wordpress",
                               base_url="https://wp.test")
    _ledger_ok(site)

    blocked = _fake_get({
        "robots.txt": (200, {}),
        "wp-sitemap.xml": (200, {}),
        "wp-json/wp/v2/settings": (200, {"blog_public": 0}),
    })
    out = service.site_health("wp-health", http_get=blocked)
    assert out["ok"] is False
    assert any("BLOCKED" in c for c in out["critical"])
    assert any("sitemap (wp-sitemap.xml): OK" in c for c in out["checks"])

    visible = _fake_get({
        "robots.txt": (200, {}),
        "wp-sitemap.xml": (404, {}),
        "wp-json/wp/v2/settings": (200, {"blog_public": 1}),
    })
    out2 = service.site_health("wp-health", http_get=visible)
    assert out2["ok"] is True and out2["critical"] == []
    assert any("search visibility: OK" in c for c in out2["checks"])
    assert any("wp-sitemap.xml): HTTP 404" in c for c in out2["checks"])
