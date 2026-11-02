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


def test_approval_is_refused_for_a_copy_of_another_article_on_the_same_site(svc):
    """SEO-05: scaled-content control is enforced where articles become `approved`, within one site only."""
    body = ("Choosing a CRM for a small agency starts with how you bill clients. Hourly billing needs time tracking "
            "built in, while retainers need recurring invoices and a clean pipeline view. ") * 6
    original = _article(svc, body, keyword="crm for agencies")
    copy = _article(svc, "# Copy\n\n" + body, keyword="agency crm guide")
    out = svc.check_article_gate(copy)
    assert out["pass"] is False and any("near-duplicate" in b for b in out["blocking"])
    # a different tenant's identical text is not compared
    from lib.db import Article, get_session
    other = svc.submit_article("other-site", keyword="crm for agencies")["id"]
    s = get_session()
    try:
        s.get(Article, other).content_md = body
        s.get(Article, other).status = "drafted"
        s.commit()
    finally:
        s.close()
    assert not any("near-duplicate" in b for b in svc.check_article_gate(other)["blocking"])
    assert original != copy


def test_the_audit_script_reports_legacy_articles_without_changing_anything(svc):
    """SEO-24: re-run existing posts through today's gate, read-only."""
    from scripts import audit_articles
    good = _article(svc, "Plain, clean prose without figures. " * 40, keyword="audit good")
    bad = _article(svc, "Costs fell 73% after the switch.", keyword="audit bad")
    before = {a: svc.get_article(a)["status"] for a in (good, bad)}
    rep = audit_articles.audit(site_slug="gate-site")
    assert rep["checked"] == 2 and rep["would_be_refused"] == 1
    refused = [r for r in rep["articles"] if not r["pass"]]
    assert refused[0]["id"] == bad and any("73%" in b for b in refused[0]["blocking"])
    assert {a: svc.get_article(a)["status"] for a in (good, bad)} == before        # nothing changed
    assert "would be refused" in audit_articles.render(rep) and "#%d" % bad in audit_articles.render(rep)
    assert "error" in audit_articles.audit(site_slug="nope")
