"""Plan SEO-01: the quality gate is enforced where articles become `approved`."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

RESEARCH = "A survey of 1,200 developers found 62% of teams use agents in production."


@pytest.fixture
def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'gate.db'}")
    monkeypatch.delenv("QUALITY_GATE_ENFORCE", raising=False)
    monkeypatch.delenv("QUALITY_GATE_CHECK_LINKS", raising=False)
    import lib.db as db
    if db._engine is not None:
        db._engine.dispose()
    db._engine = None
    db._SessionLocal = None
    from sdk import service
    service.init()
    yield service
    if db._engine is not None:
        db._engine.dispose()
    db._engine = None
    db._SessionLocal = None


def _article(svc, content, *, research=RESEARCH, meta_extra=None, keyword="gate kw"):
    """A drafted article with stored content and (optionally) stored research."""
    from lib.db import Article, KeywordLedger, get_session
    art = svc.submit_article("gate-site", keyword=keyword)
    s = get_session()
    try:
        a = s.get(Article, art["id"])
        a.content_md = content
        a.status = "drafted"
        if research and a.keyword_id:
            s.get(KeywordLedger, a.keyword_id).research_snapshot = research
        meta = dict(a.meta or {})
        meta.update(meta_extra or {})
        a.meta = meta
        s.commit()
    finally:
        s.close()
    return art["id"]


def _audit_actions(article_id):
    from lib.db import AuditLog, get_session
    s = get_session()
    try:
        return [(r.action, r.payload) for r in
                s.query(AuditLog).filter_by(article_id=article_id).order_by(AuditLog.id)]
    finally:
        s.close()


def test_unsupported_claim_refuses_approval_and_leaves_status_alone(svc):
    aid = _article(svc, "Costs fell 73% after the switch.")
    out = svc.approve_article(aid, True)
    assert out["code"] == "gate_failed"
    assert "73%" in out["error"] and "force" in out["next"]
    assert out["gate"]["pass"] is False
    assert svc.get_article(aid)["status"] == "drafted"          # NOT approved
    assert "article.gate_blocked" in [a for a, _ in _audit_actions(aid)]


def test_supported_content_approves_and_records_the_gate_result(svc):
    aid = _article(svc, "A survey of 1200 developers found strong adoption of agents in production.")
    out = svc.approve_article(aid, True)
    assert out["status"] == "approved" and out["gate"]["pass"] is True
    from lib.db import Article, get_session
    s = get_session()
    try:
        stored = s.get(Article, aid).meta["gate"]
    finally:
        s.close()
    assert stored["pass"] is True and "assessed_at" in stored


def test_force_overrides_but_is_audited_with_the_overridden_reasons(svc):
    aid = _article(svc, "Costs fell 73% after the switch.")
    out = svc.approve_article(aid, True, note="reviewed by hand", force=True)
    assert out["status"] == "approved" and out["gate"]["overridden"]
    approve = next(p for a, p in _audit_actions(aid) if a == "article.approve")
    assert approve["forced"] is True
    assert any("73%" in r for r in approve["overridden"])
    from lib.db import Article, get_session
    s = get_session()
    try:
        assert s.get(Article, aid).meta["gate"]["overridden"] is True
    finally:
        s.close()


def test_reopening_an_article_is_never_gated(svc):
    aid = _article(svc, "Costs fell 73% after the switch.")
    assert svc.approve_article(aid, False)["status"] == "needs_review"


def test_report_only_mode_assesses_but_never_refuses(svc, monkeypatch):
    monkeypatch.setenv("QUALITY_GATE_ENFORCE", "off")
    aid = _article(svc, "Costs fell 73% after the switch.")
    out = svc.approve_article(aid, True)
    assert out["status"] == "approved"
    assert out["gate"]["pass"] is False and out["gate"]["overridden"]   # still recorded


def test_failed_generation_check_blocks_even_without_research(svc):
    meta = {"generation": {"checks": {"words": {"pass": False, "value": 410, "need": 900},
                                      "tldr": {"pass": True}}}}
    aid = _article(svc, "Plain prose with no figures.", research="", meta_extra=meta)
    out = svc.approve_article(aid, True)
    assert out["code"] == "gate_failed" and "410 vs 900" in out["error"]


def test_check_article_gate_is_read_only(svc):
    aid = _article(svc, "Costs fell 73% after the switch.")
    report = svc.check_article_gate(aid)
    assert report["pass"] is False and report["enforced"] is True
    assert report["checks"]["factcheck"]["unverified"] == 1
    assert svc.get_article(aid)["status"] == "drafted"
    assert "article.gate_blocked" not in [a for a, _ in _audit_actions(aid)]
    assert "error" in svc.check_article_gate(999999)


def test_rest_returns_409_with_reasons_and_accepts_force(svc):
    from sdk.server import router
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    aid = _article(svc, "Costs fell 73% after the switch.")

    blocked = client.post(f"/sdk/v1/articles/{aid}/approve", json={"approved": True})
    assert blocked.status_code == 409
    assert "73%" in blocked.json()["detail"]

    gate = client.get(f"/sdk/v1/articles/{aid}/gate")
    assert gate.status_code == 200 and gate.json()["pass"] is False

    forced = client.post(f"/sdk/v1/articles/{aid}/approve", json={"approved": True, "force": True})
    assert forced.status_code == 200 and forced.json()["status"] == "approved"
