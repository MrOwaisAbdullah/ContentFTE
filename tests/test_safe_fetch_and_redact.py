"""Plan SEC-05 (SSRF) and SEC-11 (secrets in logs)."""
from __future__ import annotations

import socket

import pytest
import requests

from lib import safe_fetch
from lib.redact import MASK, redact_headers, redact_text, summarize
from lib.safe_fetch import UnsafeURL, check_url, safe_get, safe_request

PUBLIC = "93.184.216.34"


def resolver(mapping):
    """A getaddrinfo stand-in: {host: [ip, ...]}; IP literals resolve to themselves."""
    def _r(host, port, type=0):
        ips = mapping.get(host)
        if ips is None:
            try:
                socket.inet_pton(socket.AF_INET6 if ":" in host else socket.AF_INET, host)
                ips = [host]
            except OSError:
                raise OSError(f"unknown host {host}")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in ips]
    return _r


R = resolver({"example.test": [PUBLIC], "mixed.test": [PUBLIC, "10.0.0.5"], "evil.test": ["127.0.0.1"]})


@pytest.fixture(autouse=True)
def _strict(monkeypatch):
    monkeypatch.delenv("SAFE_FETCH_ALLOW_PRIVATE", raising=False)


# ------------------------------------------------------------------ check_url
@pytest.mark.parametrize("url", [
    "http://127.0.0.1/", "http://127.0.0.1:8000/mcp", "http://localhost/",
    "http://169.254.169.254/latest/meta-data/",          # cloud metadata
    "http://10.0.0.1/", "http://192.168.1.1/", "http://172.16.0.1/",
    "http://0.0.0.0/", "http://[::1]/", "http://[::ffff:127.0.0.1]/",
    "http://evil.test/",                                  # public-looking name -> loopback
    "http://mixed.test/",                                 # ANY private address is enough to refuse
    "file:///etc/passwd", "ftp://example.test/x", "gopher://example.test/", "javascript:alert(1)",
    "http://user:pw@example.test/", "http:///nohost",
])
def test_unsafe_urls_are_refused(url):
    with pytest.raises(UnsafeURL):
        check_url(url, resolver=R)


def test_public_urls_pass():
    assert check_url("https://example.test/a?b=1", resolver=R) == "https://example.test/a?b=1"
    assert check_url(f"http://{PUBLIC}/", resolver=R)


def test_unresolvable_hosts_are_refused_not_crashed():
    with pytest.raises(UnsafeURL):
        check_url("http://does-not-exist.test/", resolver=R)


def test_private_hosts_are_allowed_only_by_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("SAFE_FETCH_ALLOW_PRIVATE", "1")
    assert check_url("http://127.0.0.1:8080/", resolver=R)
    with pytest.raises(UnsafeURL):                               # still http(s) only
        check_url("file:///etc/passwd", resolver=R)


# ------------------------------------------------------------------ safe_request
class FakeResp:
    def __init__(self, status=200, headers=None, body=b"ok"):
        self.status_code, self.headers, self._body = status, headers or {}, body
        self.closed = False

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i:i + chunk_size]

    def close(self):
        self.closed = True

    @property
    def content(self):                      # what requests.Response exposes after a full read
        return getattr(self, "_content", b"")


def script(monkeypatch, responses):
    calls = []

    def fake(method, url, **kw):
        calls.append((method, url, kw))
        return responses.pop(0)
    monkeypatch.setattr(requests, "request", fake)
    return calls


def test_a_plain_fetch_returns_the_body_through_the_normal_response_api(monkeypatch):
    script(monkeypatch, [FakeResp(body=b"hello")])
    r = safe_request("GET", "https://example.test/x", resolver=R)
    assert r.content == b"hello" and r.status_code == 200


def test_a_redirect_into_the_private_network_is_blocked_before_it_is_requested(monkeypatch):
    calls = script(monkeypatch, [FakeResp(302, {"Location": "http://169.254.169.254/latest/meta-data/"})])
    with pytest.raises(UnsafeURL):
        safe_request("GET", "https://example.test/x", resolver=R)
    assert [c[1] for c in calls] == ["https://example.test/x"]       # the metadata URL was never fetched


def test_redirects_are_followed_when_every_hop_is_public(monkeypatch):
    calls = script(monkeypatch, [FakeResp(301, {"Location": "/final"}), FakeResp(body=b"done")])
    r = safe_request("GET", "https://example.test/start", resolver=R)
    assert r.content == b"done" and calls[1][1] == "https://example.test/final"


def test_redirect_loops_are_capped(monkeypatch):
    script(monkeypatch, [FakeResp(302, {"Location": "/again"}) for _ in range(10)])
    with pytest.raises(UnsafeURL, match="too many redirects"):
        safe_request("GET", "https://example.test/x", resolver=R)


def test_credentials_are_not_forwarded_to_a_different_host(monkeypatch):
    other = resolver({"example.test": [PUBLIC], "other.test": [PUBLIC]})
    calls = script(monkeypatch, [FakeResp(302, {"Location": "https://other.test/x"}), FakeResp()])
    safe_request("GET", "https://example.test/x", resolver=other,
                 headers={"Authorization": "Basic abc", "X-Site-Key": "k", "Accept": "text/html"}, auth=("u", "p"))
    first, second = calls[0][2], calls[1][2]
    assert first["headers"]["Authorization"] == "Basic abc" and first["auth"] == ("u", "p")
    assert "Authorization" not in second["headers"] and "X-Site-Key" not in second["headers"]
    assert second["headers"]["Accept"] == "text/html" and second["auth"] is None


def test_credentials_survive_a_same_host_redirect(monkeypatch):
    calls = script(monkeypatch, [FakeResp(302, {"Location": "/b"}), FakeResp()])
    safe_request("GET", "https://example.test/a", resolver=R, headers={"Authorization": "Basic abc"})
    assert calls[1][2]["headers"]["Authorization"] == "Basic abc"


def test_oversized_bodies_are_refused_by_header_and_by_streaming(monkeypatch):
    script(monkeypatch, [FakeResp(headers={"Content-Length": "999999"})])
    with pytest.raises(UnsafeURL, match="limit"):
        safe_request("GET", "https://example.test/x", resolver=R, max_bytes=1000)
    script(monkeypatch, [FakeResp(body=b"x" * 5000)])                # no/lying Content-Length
    with pytest.raises(UnsafeURL, match="exceeded"):
        safe_request("GET", "https://example.test/x", resolver=R, max_bytes=1000)


def test_head_requests_do_not_download_a_body(monkeypatch):
    r = FakeResp(body=b"never read")
    script(monkeypatch, [r])
    out = safe_request("HEAD", "https://example.test/x", resolver=R)
    assert out is r and not hasattr(out, "_content")


def test_every_request_carries_a_timeout_and_never_lets_requests_auto_redirect(monkeypatch):
    calls = script(monkeypatch, [FakeResp()])
    safe_request("GET", "https://example.test/x", resolver=R)
    kw = calls[0][2]
    assert kw["timeout"] and kw["allow_redirects"] is False and kw["stream"] is True


# ------------------------------------------------------------------ the real sinks
def test_the_link_validator_reports_internal_targets_as_invalid_without_requesting_them(monkeypatch):
    from lib.link_validator import _head_ok

    def boom(*a, **k):
        raise AssertionError("must not make a network request")
    monkeypatch.setattr(requests, "request", boom)
    for url in ("http://169.254.169.254/", "http://127.0.0.1:8000/mcp", "http://10.1.2.3/x"):
        assert _head_ok(url) == (False, None)


def test_fetch_url_title_will_not_touch_the_internal_network(monkeypatch):
    import asyncio
    import json

    from agents.tool_context import ToolContext

    monkeypatch.delenv("TAVILY_API_KEY", raising=False)          # importing must work without a key
    from tools.search_tools import fetch_url_title

    def fetched(*a, **k):
        raise AssertionError("an internal URL must never be requested")
    monkeypatch.setattr(requests, "request", fetched)
    url = "http://169.254.169.254/latest/meta-data/"
    args = json.dumps({"url": url})
    ctx = ToolContext(None, tool_name="fetch_url_title", tool_call_id="t1", tool_arguments=args)
    out = asyncio.run(fetch_url_title.on_invoke_tool(ctx, args))
    assert out == url                                            # falls back to the URL itself, as before


def test_search_tools_imports_and_degrades_per_call_without_a_tavily_key(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    import tools.search_tools as st
    with pytest.raises(ValueError, match="TAVILY_API_KEY"):      # raised on first USE, not at import
        st.tavily_client.search


def test_the_wordpress_connection_test_refuses_internal_hosts(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'sf.db'}")
    import lib.db as db
    if db._engine is not None:
        db._engine.dispose()
    db._engine = None
    db._SessionLocal = None
    from sdk import service
    service.init()
    service.upsert_site("wp", "WP", "wordpress", "https://example.test")
    monkeypatch.setattr(requests, "request", lambda *a, **k: (_ for _ in ()).throw(AssertionError("fetched")))
    out = service.test_wp_connection("wp", {"base_url": "http://169.254.169.254", "username": "u",
                                            "app_password": "p"})
    assert out["ok"] is False and "non-public" in out["error"]
    if db._engine is not None:
        db._engine.dispose()
    db._engine = None
    db._SessionLocal = None


# ------------------------------------------------------------------ redaction (SEC-11)
@pytest.mark.parametrize("raw,secret", [
    ("Authorization: Bearer abcdef123456.token", "abcdef123456"),
    ("GET https://ssl.bing.com/webmaster/api.svc/json/SubmitUrlBatch?apikey=SUPERSECRET123&x=1", "SUPERSECRET123"),
    ('{"password": "hunter2hunter2", "user": "bob"}', "hunter2hunter2"),
    ("X-Site-Key: cfte_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789", "AbCdEfGhIjKlMnOpQrStUvWxYz"),
    ("key sk-or-v1-abcdefghijklmnopqrstuvwx", "abcdefghijklmnopqrstuvwx"),
    ("hook https://discord.com/api/webhooks/123456789/AbCdEf_ghIJ-klmn", "AbCdEf_ghIJ"),
])
def test_credentials_are_masked_in_text(raw, secret):
    out = redact_text(raw)
    assert secret not in out and MASK in out


def test_ordinary_text_is_left_alone():
    s = "Published 3 posts for site-a in 1.2s (status=200)"
    assert redact_text(s) == s


def test_header_dicts_are_masked_by_key_name():
    out = redact_headers({"Authorization": "Bearer abc", "X-Site-Key": "k", "Content-Type": "application/json",
                          "Cookie": "s=1", "api-key": "z"})
    assert out["Content-Type"] == "application/json"
    assert all(out[k] == MASK for k in ("Authorization", "X-Site-Key", "Cookie", "api-key"))


def test_summarize_is_short_one_line_and_redacted():
    out = summarize("line1\nline2 token=abcdefgh " + "x" * 500)
    assert "\n" not in out and "abcdefgh" not in out and len(out) < 200 and "chars]" in out


def test_bing_errors_no_longer_echo_the_api_key(monkeypatch):
    from lib import indexing

    def fail(url, **kw):
        raise requests.ConnectionError(f"HTTPSConnectionPool: Max retries exceeded with url: {url}")
    monkeypatch.setattr(indexing.requests, "post", fail)
    out = indexing.submit_bing_wmt(["https://x.test/a"], site_url="https://x.test", api_key="LEAKYAPIKEY12345")
    assert out["ok"] is False and out["error"]
    assert "LEAKYAPIKEY12345" not in repr(out)


@pytest.mark.parametrize("raw,secret", [
    ("could not connect to postgresql://app:Sup3rSecretPw@ep-x.neon.tech/db", "Sup3rSecretPw"),
    ("redis://:onlypassword@cache:6379/0", "onlypassword"),
    ("mysql+pymysql://root:rootpw99@127.0.0.1/app?charset=utf8", "rootpw99"),
])
def test_credentials_embedded_in_connection_urls_are_masked(raw, secret):
    out = redact_text(raw)
    assert secret not in out
    assert out.split("://", 1)[0] in raw            # scheme and host survive, so the log is still useful


def test_urls_without_credentials_are_untouched():
    s = "fetching https://example.com:8443/path?x=1 and postgresql://db.internal:5432/app"
    assert redact_text(s) == s


# ---- SEC-19: the screenshot browser re-validates every request, not just the first URL ------------------
def test_screenshot_url_check_uses_the_shared_guard():
    from tools.screenshot_tool import _url_is_safe_public
    for bad in ("http://127.0.0.1:8000/", "http://169.254.169.254/latest/meta-data/", "file:///etc/passwd",
                "http://user:pw@example.com/", "ftp://example.com/x", "http://[::1]/"):
        assert _url_is_safe_public(bad), bad


def test_request_guard_aborts_internal_subrequests_and_allows_data_urls():
    import asyncio
    from tools.screenshot_tool import _install_request_guard

    class _Req:
        def __init__(self, url): self.url = url

    class _Route:
        def __init__(self, url): self.request, self.action = _Req(url), None
        async def abort(self, reason): self.action = ("abort", reason)
        async def continue_(self): self.action = ("continue",)

    class _Page:
        async def route(self, pattern, handler): self.handler = handler

    async def run():
        page, blocked = _Page(), []
        await _install_request_guard(page, blocked)
        internal, data = _Route("http://169.254.169.254/latest/"), _Route("data:image/png;base64,AAAA")
        await page.handler(internal)
        await page.handler(data)
        return internal, data, blocked

    internal, data, blocked = asyncio.run(run())
    assert internal.action[0] == "abort" and data.action == ("continue",)
    assert blocked and "169.254.169.254" in blocked[0]["url"]


# ---- SEC-20 / PIPE-14: model-chosen URLs -------------------------------------------------------------------
def test_url_guard_blocks_data_in_the_url_to_unseen_hosts_but_allows_plain_source_links():
    from tools import url_guard as g
    g.reset()
    assert g.check_model_url("https://source.example/guide/page") is None                     # plain source link
    assert g.check_model_url("https://attacker.example/?d=UNPUBLISHED-DRAFT-TEXT")           # exfil form
    assert g.check_model_url("https://attacker.example/p#" + "x" * 50)
    assert g.check_model_url("https://u:p@x.example/")
    assert g.check_model_url("file:///etc/passwd") and g.check_model_url("javascript:alert(1)")
    assert g.check_model_url("https://x.example/" + "a/" * 20)
    g.remember_results(["https://news.example/story?id=5"])
    assert g.check_model_url("https://news.example/other?page=2") is None                     # host came from a search


def test_crawl_arguments_are_clamped_and_priced_by_size():
    from tools import url_guard as g
    assert g.clamp_crawl(99, 5000) == (3, 20) and g.clamp_crawl(-1, 0) == (1, 1) and g.clamp_crawl("x", None) == (2, 10)
    assert g.crawl_cost(1) == 1 and g.crawl_cost(5) == 1 and g.crawl_cost(20) == 4


def test_title_fetches_are_capped_per_run():
    from tools import url_guard as g
    g.reset()
    assert all(g.allow_title_fetch() for _ in range(g.MAX_TITLE_FETCHES_PER_RUN))
    assert g.allow_title_fetch() is False
    g.reset()
    assert g.allow_title_fetch() is True


def test_the_tools_apply_the_guard(monkeypatch):
    import asyncio
    import json
    from tools import search_tools, url_guard as g
    g.reset()
    called = []

    class Stub:
        async def extract(self, **k):
            called.append(("extract", k))
            return {"results": []}

        async def crawl(self, **k):
            called.append(("crawl", k))
            return {"results": []}

    monkeypatch.setattr(search_tools, "tavily_client", Stub())
    monkeypatch.setattr("lib.tavily_meter.meter", lambda site_slug="", n=1: {"allowed": True})

    from agents.tool_context import ToolContext

    def call(tool, args):
        raw = json.dumps(args)
        ctx = ToolContext(None, tool_name=tool.name, tool_call_id="t", tool_arguments=raw)
        return asyncio.run(tool.on_invoke_tool(ctx, raw))

    bad = call(search_tools.tavily_extract_tool, {"urls": ["https://attacker.example/?d=secret"]})
    assert "Refused" in str(bad) and called == []
    bad = call(search_tools.tavily_crawl_tool, {"start_url": "https://attacker.example/?d=secret"})
    assert "Refused" in str(bad) and called == []
    call(search_tools.tavily_crawl_tool, {"start_url": "https://docs.example/guide", "max_depth": 50, "limit": 9999})
    assert called[0][0] == "crawl" and called[0][1]["max_depth"] == 3 and called[0][1]["limit"] == 20
    assert search_tools.fetch_url_title.on_invoke_tool is not None
