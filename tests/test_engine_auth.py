"""Plan SEC-01 / SEC-02: one fail-closed API-key check in front of REST *and* /mcp.

Before: `/mcp` was mounted with no authentication at all, and an unset
`SDK_MASTER_KEY` silently opened every `/sdk/v1` route (compared with `!=`).
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.responses import PlainTextResponse

from sdk.auth import KeyAuthMiddleware, bearer_token, check_key, keys_equal
from sdk.server import router


def _rest_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


async def _inner_app(scope, receive, send):
    """Stand-in for the mounted MCP app: if a request reaches it, auth passed."""
    if scope["type"] == "http":
        await PlainTextResponse("reached-inner-app")(scope, receive, send)


def _mcp_client() -> TestClient:
    app = FastAPI()
    app.mount("/mcp", KeyAuthMiddleware(_inner_app))
    return TestClient(app)


@pytest.fixture
def closed(monkeypatch):
    """No key configured and no explicit dev opt-in (the production default)."""
    monkeypatch.delenv("SDK_MASTER_KEY", raising=False)
    monkeypatch.delenv("SDK_ALLOW_UNAUTHENTICATED", raising=False)


def test_unset_key_fails_closed_on_rest(closed):
    r = _rest_client().get("/sdk/v1/sites")
    assert r.status_code == 503
    assert "SDK_MASTER_KEY" in r.json()["detail"]


def test_unset_key_fails_closed_on_mcp(closed):
    r = _mcp_client().post("/mcp/", json={})
    assert r.status_code == 503
    assert "reached-inner-app" not in r.text


def test_explicit_dev_opt_in_still_allows_local_use(closed, monkeypatch):
    monkeypatch.setenv("SDK_ALLOW_UNAUTHENTICATED", "1")
    assert check_key(None) == "dev"
    assert _mcp_client().post("/mcp/", json={}).text == "reached-inner-app"


def test_mcp_requires_the_key_when_configured(closed, monkeypatch):
    monkeypatch.setenv("SDK_MASTER_KEY", "sekret")
    c = _mcp_client()
    assert c.post("/mcp/", json={}).status_code == 401
    assert c.post("/mcp/", json={}, headers={"X-Site-Key": "wrong"}).status_code == 401
    assert c.post("/mcp/", json={}, headers={"Authorization": "Basic sekret"}).status_code == 401
    ok_header = c.post("/mcp/", json={}, headers={"X-Site-Key": "sekret"})
    ok_bearer = c.post("/mcp/", json={}, headers={"Authorization": "Bearer sekret"})
    assert ok_header.text == ok_bearer.text == "reached-inner-app"


def test_rest_requires_the_key_when_configured(closed, monkeypatch):
    monkeypatch.setenv("SDK_MASTER_KEY", "sekret")
    c = _rest_client()
    assert c.get("/sdk/v1/sites").status_code == 401
    assert c.get("/sdk/v1/sites", headers={"X-Site-Key": "nope"}).status_code == 401
    assert c.get("/sdk/v1/sites", headers={"X-Site-Key": "sekret"}).status_code == 200


def test_a_blank_configured_key_is_not_a_wildcard(closed, monkeypatch):
    monkeypatch.setenv("SDK_MASTER_KEY", "   ")
    assert _rest_client().get("/sdk/v1/sites").status_code == 503


def test_key_comparison_helpers():
    assert keys_equal("abc", "abc")
    assert not keys_equal("abc", "abd")
    assert not keys_equal("abc", "ab")
    assert not keys_equal(None, "abc")
    assert not keys_equal("", "")          # empty never matches empty
    assert keys_equal("ключ", "ключ")      # non-ASCII keys don't crash the comparison
    assert bearer_token("Bearer  tok ") == "tok"
    assert bearer_token("bearer tok") == "tok"
    assert bearer_token("Basic tok") is None
    assert bearer_token(None) is None
