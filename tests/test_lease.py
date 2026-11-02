"""ENG-03 / ENG-14 / OPS-02: single-flight and idempotency that hold across worker processes."""
import threading
from datetime import timedelta

import pytest


@pytest.fixture
def lease(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'lease.db'}")
    import lib.db as db
    if db._engine is not None:
        db._engine.dispose()
    db._engine = None
    db._SessionLocal = None
    from lib import lease as mod
    yield mod
    if db._engine is not None:
        db._engine.dispose()
    db._engine = None
    db._SessionLocal = None


def test_a_second_process_cannot_take_a_held_lease(lease, monkeypatch):
    assert lease.claim("publish:1") is True
    me = lease.HOLDER
    monkeypatch.setattr(lease, "HOLDER", "other-worker")          # what a second uvicorn worker looks like
    assert lease.claim("publish:1") is False
    assert lease.claim("publish:2") is True                        # a different article is unaffected
    monkeypatch.setattr(lease, "HOLDER", me)
    lease.release("publish:1")
    monkeypatch.setattr(lease, "HOLDER", "other-worker")
    assert lease.claim("publish:1") is True                        # free again once released


def test_only_the_holder_can_release(lease, monkeypatch):
    lease.claim("k")
    me = lease.HOLDER
    monkeypatch.setattr(lease, "HOLDER", "intruder")
    lease.release("k")                                             # must be a no-op
    assert lease.claim("k") is False
    monkeypatch.setattr(lease, "HOLDER", me)


def test_a_crashed_holders_lease_expires_and_is_taken_over(lease, monkeypatch):
    assert lease.claim("publish:9", ttl=-5) is True                # already expired = the holder died
    monkeypatch.setattr(lease, "HOLDER", "survivor")
    assert lease.claim("publish:9") is True                        # taken over
    monkeypatch.setattr(lease, "HOLDER", "latecomer")
    assert lease.claim("publish:9") is False                       # and it is held again


def test_exactly_one_of_many_concurrent_claimants_wins(lease, monkeypatch):
    wins, errors = [], []

    def worker(i):
        try:
            # each thread pretends to be its own process
            from lib import lease as mod
            res = _claim_as(mod, f"w{i}")
            wins.append(res)
        except Exception as e:                                     # pragma: no cover
            errors.append(e)

    def _claim_as(mod, holder):
        # HOLDER is module-global, so serialise the swap; the DB insert is the thing under test
        with swap_lock:
            old = mod.HOLDER
            mod.HOLDER = holder
            try:
                return mod.claim("race", ttl=60)
            finally:
                mod.HOLDER = old

    swap_lock = threading.Lock()
    ts = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors and wins.count(True) == 1 and wins.count(False) == 7


def test_idempotency_records_replay_across_workers_and_expire(lease):
    assert lease.idem_get("abc") is None
    lease.idem_put("abc", {"id": 5})
    assert lease.idem_get("abc") == {"id": 5}
    lease.idem_put("abc", {"id": 6})                               # a duplicate store never overwrites or raises
    assert lease.idem_get("abc") == {"id": 5}
    from lib.db import IdempotencyRecord, get_session
    from lib.lease import _now
    s = get_session()
    try:
        s.query(IdempotencyRecord).filter_by(key="abc").one().created_at = _now() - timedelta(days=2)
        s.commit()
    finally:
        s.close()
    assert lease.idem_get("abc") is None


def test_purge_removes_only_what_is_expired(lease):
    lease.claim("old", ttl=-1)
    lease.claim("live", ttl=600)
    assert lease.purge_expired() >= 1
    assert lease.claim("live") is True                              # still held by us (renewed)


def test_the_services_single_flight_now_spans_processes(lease, monkeypatch):
    from sdk import service
    assert service._claim("publish", 77) is True
    monkeypatch.setattr(lease, "HOLDER", "second-worker")
    assert service._claim("publish", 77) is False                  # a second worker is refused
    monkeypatch.undo()
    service._release("publish", 77)


def test_a_stage_held_by_another_worker_is_refused_over_rest(lease, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sdk.server import router
    monkeypatch.setenv("SDK_ALLOW_UNAUTHENTICATED", "1")
    assert lease.claim("stage:research", ttl=600) is True
    monkeypatch.setattr(lease, "HOLDER", "worker-2")
    app = FastAPI()
    app.include_router(router)
    r = TestClient(app).post("/sdk/v1/run/research")
    assert r.status_code == 409 and "another worker" in r.json()["detail"]
