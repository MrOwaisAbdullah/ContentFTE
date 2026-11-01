"""PIPE-08: /run_workflow used to import a symbol that does not exist -> every call was a 500."""
import pytest


@pytest.fixture
def client(monkeypatch):
    for k in ("OPENROUTER_API_KEY", "GEMINI_API_KEY", "TAVILY_API_KEY"):
        monkeypatch.setenv(k, "test")
    from fastapi.testclient import TestClient
    import main
    main.app.dependency_overrides[main.verify_api_key] = lambda: "ok"
    yield main, TestClient(main.app)
    main.app.dependency_overrides.clear()


def _stub(main, monkeypatch, messages, calls):
    def make(name):
        async def _stage(api_key=""):
            calls.append(name)
            return {"status": "success", "message": messages[name]}
        return _stage
    monkeypatch.setitem(main._WORKFLOW_STAGES, "research", ("research", lambda: make("research")()))
    monkeypatch.setitem(main._WORKFLOW_STAGES, "brief", ("brief", lambda: make("brief")()))
    monkeypatch.setitem(main._WORKFLOW_STAGES, "content", ("content", lambda: make("content")()))
    monkeypatch.setitem(main._WORKFLOW_STAGES, "posting", ("posting", lambda: make("posting")()))


def test_the_route_no_longer_imports_missing_symbols(client):
    main, c = client
    src = open(main.__file__, encoding="utf-8").read()
    assert "run_content_generation_workflow" not in src


def test_single_stage(client, monkeypatch):
    main, c = client
    calls = []
    _stub(main, monkeypatch, dict.fromkeys(("research", "brief", "content", "posting"), "done"), calls)
    r = c.post("/run_workflow", json={"workflow_type": "brief"})
    assert r.status_code == 200, r.text
    assert calls == ["brief"] and r.json()["workflows_completed"] == ["brief"]


def test_full_runs_every_stage_in_order(client, monkeypatch):
    main, c = client
    calls = []
    _stub(main, monkeypatch, dict.fromkeys(("research", "brief", "content", "posting"), "done"), calls)
    r = c.post("/run_workflow", json={"workflow_type": "full"})
    assert calls == ["research", "brief", "content", "posting"]
    assert r.json()["stopped_early"] is False


def test_full_stops_when_a_stage_has_nothing_to_hand_on(client, monkeypatch):
    main, c = client
    calls = []
    msgs = {"research": "ok", "brief": "Content brief generation completed with issues: x", "content": "ok", "posting": "ok"}
    _stub(main, monkeypatch, msgs, calls)
    body = c.post("/run_workflow", json={"workflow_type": "full"}).json()
    assert calls == ["research", "brief"] and body["stopped_early"] is True


def test_invalid_type_is_a_422_not_a_500(client):
    _, c = client
    assert c.post("/run_workflow", json={"workflow_type": "nope"}).status_code == 422
