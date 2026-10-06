"""Brief-agent wiring (TASKS A0): §5.16 ledger gating, intent templates,
discourse appendix + SERP-gap instructions, ledger lifecycle close."""
import pytest


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch):
    import os

    workdir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           ".test-tmp-phase1")
    os.makedirs(workdir, exist_ok=True)
    db_file = os.path.join(workdir, "brief.db")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("SEO_DATA_PROVIDER", "off")
    import lib.db as db

    if db._engine is not None:
        db._engine.dispose()
    db._engine = None
    db._SessionLocal = None
    try:
        os.remove(db_file)
    except OSError:
        pass
    db.init_db()
    yield
    if db._engine is not None:
        db._engine.dispose()
    try:
        os.remove(db_file)
    except OSError:
        pass


def _first_site_id():
    from sqlalchemy import select

    from lib.db import Site, get_session

    s = get_session()
    try:
        site = s.execute(select(Site).order_by(Site.id.asc())).scalars().first()
        return site.id if site else None
    finally:
        s.close()


def _seed_site_and_row(status: str, keyword: str = "kw one",
                       intent: str = "commercial", volume: int = 100,
                       difficulty: float = 20.0):
    from lib.db import Site, get_session
    from lib.ledger import set_status, upsert_keyword

    s = get_session()
    try:
        site = Site(slug="wired", name="Wired")
        s.add(site)
        s.commit()
        s.refresh(site)
        row = upsert_keyword(s, site.id, keyword, intent=intent,
                             volume=volume, difficulty=difficulty)
        if status != "researched":
            row = set_status(s, row.id, status)
        return site.id, row.id
    finally:
        s.close()


def test_intent_templates_cover_all_intents():
    from lib.brief_templates import TEMPLATES, template_for, template_text
    from lib.ledger import INTENT_VALUE

    for intent in INTENT_VALUE:
        t = template_for(intent)
        assert t["intent"] == intent
        assert t["required_sections"] and t["h2_pattern"] and t["cta_posture"]
        assert "3" in t["serp_gap_rule"]  # exactly-3 SERP-gap rule
        assert "Sources box" in " ".join(t["required_sections"])
        rendered = template_text(intent)
        assert t["name"] in rendered and "SERP gaps:" in rendered

    # unknown / empty intents fall back to informational (never break a brief)
    assert template_for("definitely-not-an-intent")["intent"] == "informational"
    assert template_for("")["intent"] == "informational"
    assert set(TEMPLATES) >= set(INTENT_VALUE)


def test_brief_task_gating_only_approved_or_queued():
    from tools.ledger_tool import get_next_brief_task

    # researched-only ledger -> nothing briefable
    _seed_site_and_row("researched", keyword="not yet", volume=999)
    assert get_next_brief_task()["status"] == "error"

    # an approved row becomes pullable, with its intent template attached
    from lib.db import get_session
    from lib.ledger import set_status, upsert_keyword

    s = get_session()
    try:
        row = upsert_keyword(s, _first_site_id(), "approved kw",
                             intent="transactional", volume=50, difficulty=10.0)
        set_status(s, row.id, "approved")
    finally:
        s.close()

    task = get_next_brief_task()
    assert task["status"] == "ok"
    assert task["keyword"] == "approved kw"
    assert task["intent"] == "transactional"
    assert task["template"]["intent"] == "transactional"
    assert task["template_text"]
    # higher priority (volume 999 informational vs 50 transactional) never
    # leaks a non-briefable row: the researched row stayed out
    assert task["status_label"] == "approved"


def test_register_bridges_then_mark_briefed_closes_loop():
    from lib.db import get_session
    from lib.ledger import set_status, upsert_keyword
    from tools.ledger_tool import (get_next_brief_task, mark_brief_saved,
                                   register_brief_task)

    # no site yet -> register creates the default site and queues the row
    reg = register_brief_task("bridge kw", intent="informational")
    assert reg["status"] == "ok" and reg["status_label"] == "queued"

    task = get_next_brief_task()
    assert task["status"] == "ok" and task["keyword"] == "bridge kw"

    # close the loop -> row leaves the briefable queue
    done = mark_brief_saved("bridge kw")
    assert done["status"] == "ok" and done["status_label"] == "briefed"
    # second close is idempotent (already past briefing)
    again = mark_brief_saved("bridge kw")
    assert again.get("already") is True
    assert get_next_brief_task()["status"] == "error"

    # register never downgrades an approved row
    s = get_session()
    try:
        row = upsert_keyword(s, _first_site_id(), "keep approved",
                             intent="commercial")
        set_status(s, row.id, "approved")
    finally:
        s.close()
    reg2 = register_brief_task("keep approved")
    assert reg2["status"] == "ok" and reg2["status_label"] == "approved"


def test_mark_brief_saved_requires_ledger_row():
    from tools.ledger_tool import mark_brief_saved

    _seed_site_and_row("approved", keyword="real kw")
    err = mark_brief_saved("ghost keyword")
    assert err["status"] == "error" and "no ledger row" in err["message"]


def test_brief_agent_wired_for_ledger_discourse_serp_gap():
    from blog_agent.blog_agents import brief_agent

    tool_names = {t.name for t in brief_agent.tools}
    assert {"get_next_brief_task_tool", "register_brief_task_tool",
            "get_brief_template_tool", "mark_brief_saved_tool"} <= tool_names

    instr = brief_agent.instructions
    for marker in ("get_next_brief_task_tool", "register_brief_task_tool",
                   "get_brief_template_tool", "mark_brief_saved_tool",
                   "Discourse Appendix", "SERP Gaps",
                   "time_range=\"month\"", "EXACTLY 3 missed subtopics",
                   "approved/queued"):
        assert marker in instr, f"brief agent instructions missing: {marker}"
