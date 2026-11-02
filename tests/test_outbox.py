"""ADP-04: a failed custom-site delivery is kept and retried, under the same delivery id."""
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'ob.db'}")
    monkeypatch.delenv("SECRETS_KEY", raising=False)
    import lib.db as db
    if db._engine is not None:
        db._engine.dispose()
    db._engine = None
    db._SessionLocal = None
    from sdk import service
    service.init()
    service.upsert_site("hooked", "H", "custom", "https://hooked.test",
                        {"require_approval": False, "delivery": {"webhook_url": "https://hooked.test/hook", "secret": "k"}})
    yield service
    if db._engine is not None:
        db._engine.dispose()
    db._engine = None
    db._SessionLocal = None


def _publish(svc, monkeypatch, outcome):
    from lib import custom_site
    from lib.db import Article, get_session
    calls = []

    def fake(payload, webhook_url="", secret="", delivery_id="", **kw):
        calls.append({"url": webhook_url, "secret": secret, "id": delivery_id})
        return dict(outcome, delivery_id=delivery_id or "first-id", attempts=1)

    monkeypatch.setattr(custom_site, "deliver", fake)
    aid = svc.submit_article("hooked", keyword="outbox kw")["id"]
    s = get_session()
    try:
        a = s.get(Article, aid)
        a.status, a.content_md = "approved", "# T\n\nbody"
        s.commit()
    finally:
        s.close()
    return svc.publish_article(aid), calls


def test_a_failed_delivery_is_queued_and_a_good_one_is_not(svc, monkeypatch):
    from lib.outbox import pending_summary
    ok, _ = _publish(svc, monkeypatch, {"status": "ok", "status_code": 200})
    assert ok["delivery"]["status"] == "ok" and pending_summary() == {"pending": 0, "dead": 0}
    bad, _ = _publish(svc, monkeypatch, {"status": "error", "message": "HTTP 503"})
    assert bad["delivery"]["queued"] is True and pending_summary()["pending"] == 1


def test_the_retry_reuses_the_delivery_id_resigns_with_the_current_secret_and_marks_delivered(svc, monkeypatch):
    from lib import outbox
    from lib.db import DeliveryOutbox, get_session
    _publish(svc, monkeypatch, {"status": "error", "message": "HTTP 503"})
    s = get_session()
    try:
        row = s.query(DeliveryOutbox).one()
        assert "secret" not in row.payload and row.delivery_id == "first-id"        # no key stored in the outbox
        original = row.delivery_id
    finally:
        s.close()
    seen = []
    later = datetime.now(timezone.utc) + timedelta(hours=1)
    res = outbox.process_due(now=later, send=lambda payload, **kw: seen.append(kw) or {"status": "ok", "status_code": 200})
    assert res == {"sent": 1, "retried": 0, "dead": 0}
    assert seen[0]["delivery_id"] == original and seen[0]["secret"] == "k" and seen[0]["max_attempts"] == 1
    s = get_session()
    try:
        assert s.query(DeliveryOutbox).one().status == "delivered"
    finally:
        s.close()
    assert outbox.process_due(now=later, send=lambda *a, **k: pytest.fail("nothing left to send")) == \
        {"sent": 0, "retried": 0, "dead": 0}


def test_a_delivery_is_not_retried_before_its_time_and_gives_up_after_the_last_attempt(svc, monkeypatch):
    from lib import outbox
    from lib.db import DeliveryOutbox, get_session
    _publish(svc, monkeypatch, {"status": "error", "message": "HTTP 500"})
    boom = lambda payload, **kw: {"status": "error", "message": "HTTP 500"}           # noqa: E731
    assert outbox.process_due(now=datetime.now(timezone.utc), send=lambda *a, **k: pytest.fail("too early")) == \
        {"sent": 0, "retried": 0, "dead": 0}
    far = datetime.now(timezone.utc) + timedelta(days=30)
    tally = {"retried": 0, "dead": 0}
    for i in range(outbox.MAX_ATTEMPTS + 2):
        r = outbox.process_due(now=far + timedelta(hours=7 * i), send=boom)     # time passes between passes
        tally["retried"] += r["retried"]
        tally["dead"] += r["dead"]
    assert tally["dead"] == 1 and tally["retried"] >= 1
    assert outbox.pending_summary() == {"pending": 0, "dead": 1}
    s = get_session()
    try:
        assert s.query(DeliveryOutbox).one().status == "dead"
    finally:
        s.close()


def test_dead_deliveries_raise_an_alert(svc, monkeypatch):
    from lib import outbox
    from sdk.ops import collect_alerts
    _publish(svc, monkeypatch, {"status": "error", "message": "HTTP 500"})
    far = datetime.now(timezone.utc) + timedelta(days=30)
    for i in range(outbox.MAX_ATTEMPTS + 1):
        outbox.process_due(now=far + timedelta(hours=7 * i), send=lambda *a, **k: {"status": "error", "message": "HTTP 500"})
    assert "delivery_failed" in {a["code"] for a in collect_alerts()}


def test_deliver_honors_a_supplied_delivery_id(monkeypatch):
    from lib import custom_site

    class R:
        status_code = 200

    seen = []
    monkeypatch.setattr(custom_site.requests, "post", lambda url, **kw: seen.append(kw["headers"]) or R())
    out = custom_site.deliver({"a": 1}, webhook_url="https://h.test/x", delivery_id="keep-me")
    assert out["delivery_id"] == "keep-me" and seen[0]["X-CFTE-Delivery"] == "keep-me"
