"""Plan ENG-21 / ENG-15: a readiness probe that tells the truth, and schema creation that runs once."""
from __future__ import annotations

import pytest


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'ready.db'}")
    import lib.db as db
    if db._engine is not None:
        db._engine.dispose()
    db._engine = None
    db._SessionLocal = None
    yield db
    if db._engine is not None:
        db._engine.dispose()
    db._engine = None
    db._SessionLocal = None


def test_ready_when_the_database_answers_and_a_key_is_configured(fresh_db, monkeypatch):
    from sdk.health import readiness
    monkeypatch.setenv("SDK_MASTER_KEY", "k")
    out = readiness()
    assert out["ready"] is True
    assert out["checks"]["database"] == {"ok": True, "dialect": "sqlite"}
    assert out["checks"]["auth"]["master_key_configured"] is True


def test_not_ready_when_no_key_is_set_because_every_request_would_be_refused(fresh_db, monkeypatch):
    from sdk.health import readiness
    monkeypatch.delenv("SDK_MASTER_KEY", raising=False)
    monkeypatch.delenv("SDK_ALLOW_UNAUTHENTICATED", raising=False)
    out = readiness()
    assert out["ready"] is False and out["checks"]["auth"]["ok"] is False
    assert "SDK_MASTER_KEY" in out["checks"]["auth"]["error"]
    assert out["checks"]["database"]["ok"] is True                    # the DB part is still reported honestly


def test_explicit_dev_mode_counts_as_ready_and_is_labelled(fresh_db, monkeypatch):
    from sdk.health import readiness
    monkeypatch.delenv("SDK_MASTER_KEY", raising=False)
    monkeypatch.setenv("SDK_ALLOW_UNAUTHENTICATED", "1")
    out = readiness()
    assert out["ready"] is True and out["checks"]["auth"]["unauthenticated_dev_mode"] is True


def test_an_unreachable_database_is_not_ready_and_its_error_is_redacted(monkeypatch):
    import lib.db as db
    from sdk.health import readiness
    monkeypatch.setenv("SDK_MASTER_KEY", "k")

    def broken():
        raise RuntimeError("could not connect to postgresql://user:hunter2hunter2@db.example/x?password=hunter2hunter2")
    monkeypatch.setattr(db, "get_engine", broken)
    out = readiness()
    assert out["ready"] is False and out["checks"]["database"]["ok"] is False
    assert "hunter2hunter2" not in repr(out)


def test_readiness_never_leaks_the_key(fresh_db, monkeypatch):
    from sdk.health import readiness
    monkeypatch.setenv("SDK_MASTER_KEY", "super-secret-master-key")
    assert "super-secret-master-key" not in repr(readiness())


def test_the_ready_route_maps_the_result_to_200_or_503(fresh_db, monkeypatch):
    for k in ("OPENROUTER_API_KEY", "GEMINI_API_KEY", "TAVILY_API_KEY"):
        monkeypatch.setenv(k, "test")
    from fastapi.testclient import TestClient
    from main import app
    c = TestClient(app)                          # no lifespan: only routing is exercised
    monkeypatch.setenv("SDK_MASTER_KEY", "k")
    assert c.get("/ready").status_code == 200
    monkeypatch.delenv("SDK_MASTER_KEY", raising=False)
    monkeypatch.delenv("SDK_ALLOW_UNAUTHENTICATED", raising=False)
    r = c.get("/ready")
    assert r.status_code == 503 and r.json()["ready"] is False
    assert c.get("/health").status_code == 200   # liveness is unchanged


def test_schema_creation_runs_once_per_engine(fresh_db, monkeypatch):
    calls = []
    real = fresh_db.Base.metadata.create_all
    monkeypatch.setattr(fresh_db.Base.metadata, "create_all", lambda eng: calls.append(1) or real(eng))
    for _ in range(5):
        fresh_db.init_db()
    assert len(calls) == 1                       # was one catalogue sweep per service call
    # a new engine (restart / reset) re-checks, so a fresh database still gets its tables
    fresh_db._engine = None
    fresh_db._SessionLocal = None
    fresh_db.init_db()
    assert len(calls) == 2


def test_schema_is_recreated_if_the_sqlite_file_disappears_under_a_live_engine(fresh_db, tmp_path):
    """Regression: a deleted SQLite file made init_db's once-per-engine shortcut lie ('tables exist'),
    surfacing as `no such table`. The old every-call create_all hid it."""
    import os
    from sqlalchemy import inspect

    fresh_db.init_db()
    eng = fresh_db.get_engine()
    assert "api_keys" in inspect(eng).get_table_names()

    eng.dispose()
    os.remove(eng.url.database)                       # file vanishes; the cached engine object stays
    fresh_db.init_db()                                # must notice and rebuild, not short-circuit
    assert "api_keys" in inspect(fresh_db.get_engine()).get_table_names()
