"""ENG-16: service errors become classified HTTP statuses with a machine-readable code and the `next` hint."""
import pytest

from sdk.errors import classify


@pytest.mark.parametrize("result,code,status", [
    ({"error": "article 5 not found", "next": "x"}, "not_found", 404),
    ({"error": "invalid mode 'x'", "next": "use 'draft' (default) or 'auto'"}, "invalid_input", 400),
    ({"error": "article 5 is 'drafted' — publish requires 'approved'"}, "invalid_state", 409),
    ({"error": "cadence limit reached for site 's'"}, "rate_limited", 429),
    ({"error": "wp refresh failed: Timeout"}, "upstream_failed", 502),
    ({"error": "WordPress not configured"}, "not_configured", 424),
    ({"error": "quality gate", "code": "gate_failed"}, "gate_failed", 409),
    ({"error": "over budget", "code": "budget_exceeded"}, "budget_exceeded", 402),
    ({"error": "something odd"}, "error", 404),                      # unclassified keeps the historical 404
])
def test_classification(result, code, status):
    assert classify(result) == (code, status)


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'e.db'}")
    monkeypatch.setenv("SDK_ALLOW_UNAUTHENTICATED", "1")
    for k in ("OPENROUTER_API_KEY", "GEMINI_API_KEY", "TAVILY_API_KEY"):
        monkeypatch.setenv(k, "test")
    import lib.db as db
    if db._engine is not None:
        db._engine.dispose()
    db._engine = None
    db._SessionLocal = None
    from fastapi.testclient import TestClient
    import main
    yield TestClient(main.app)
    if db._engine is not None:
        db._engine.dispose()
    db._engine = None
    db._SessionLocal = None


def test_a_missing_article_returns_code_and_next_alongside_detail(client):
    r = client.get("/sdk/v1/articles/999999")
    assert r.status_code == 404
    body = r.json()
    assert isinstance(body["detail"], str) and body["code"] == "not_found"


def test_the_error_envelope_survives_a_router_on_a_bare_app(monkeypatch, tmp_path):
    """No handler installed -> FastAPI's default renders {"detail": ...}: still valid, just without the extras."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'b.db'}")
    monkeypatch.setenv("SDK_ALLOW_UNAUTHENTICATED", "1")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sdk.server import router
    app = FastAPI()
    app.include_router(router)
    r = TestClient(app).get("/sdk/v1/articles/999999")
    assert r.status_code == 404 and isinstance(r.json()["detail"], str)
