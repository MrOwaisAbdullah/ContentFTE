"""ENG-21 request ids + structured logs; SEC-15 docs gating and the shared-mode CORS default."""
import json
import logging

import pytest


@pytest.fixture
def client(monkeypatch):
    for k in ("OPENROUTER_API_KEY", "GEMINI_API_KEY", "TAVILY_API_KEY"):
        monkeypatch.setenv(k, "test")
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app)


def test_every_response_carries_a_request_id(client):
    r = client.get("/health")
    rid = r.headers["x-request-id"]
    assert len(rid) >= 8


def test_a_sane_caller_id_is_echoed_and_a_hostile_one_is_replaced(client):
    assert client.get("/health", headers={"X-Request-ID": "console-abc12345"}).headers["x-request-id"] == "console-abc12345"
    bad = client.get("/health", headers={"X-Request-ID": "x y\t<script>"}).headers["x-request-id"]
    assert bad != "x y\t<script>" and "<" not in bad


def test_docs_and_openapi_are_off_by_default(client):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_docs_can_be_switched_on(monkeypatch):
    monkeypatch.setenv("ENGINE_DOCS", "1")
    import main
    assert main._docs_enabled() is True
    monkeypatch.setenv("ENGINE_DOCS", "0")
    assert main._docs_enabled() is False


def test_json_formatter_carries_request_id_and_never_the_query(client, caplog):
    from sdk.observability import JsonFormatter, RequestIdFilter
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "hello %s", ("world",), None)
    RequestIdFilter().filter(rec)
    out = json.loads(JsonFormatter().format(rec))
    assert out["msg"] == "hello world" and out["level"] == "INFO" and "request_id" in out

    with caplog.at_level(logging.INFO, logger="contentfte.access"):
        client.get("/?token=SECRET-IN-QUERY")
    text = " ".join(r.getMessage() + str(getattr(r, "path", "")) for r in caplog.records)
    assert "SECRET-IN-QUERY" not in text


def test_shared_mode_has_no_cors_wildcard_by_default(monkeypatch):
    import importlib
    monkeypatch.setenv("TENANCY_MODE", "shared")
    monkeypatch.delenv("SDK_CORS_ORIGINS", raising=False)
    import main
    importlib.reload(main)
    assert main._sdk_cors_origins == []
    monkeypatch.setenv("TENANCY_MODE", "isolated")
    importlib.reload(main)
    assert main._sdk_cors_origins == ["*"]
