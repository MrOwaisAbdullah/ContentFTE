"""OPS-01: error tracking scrub, backups, operational alerts."""
import sqlite3
import sys
import types
from datetime import datetime, timedelta, timezone

import pytest


# ------------------------------------------------------------------ Sentry
def test_sentry_is_off_without_a_dsn_and_never_raises(monkeypatch):
    from sdk import monitoring
    monkeypatch.setattr(monitoring, "_initialised", False)
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    assert monitoring.init_sentry() is False


def test_sentry_with_a_dsn_but_no_package_degrades_quietly(monkeypatch):
    from sdk import monitoring
    monkeypatch.setattr(monitoring, "_initialised", False)
    monkeypatch.setenv("SENTRY_DSN", "https://k@example.ingest.sentry.io/1")
    monkeypatch.setitem(sys.modules, "sentry_sdk", None)              # `import sentry_sdk` -> ImportError
    assert monitoring.init_sentry() is False


def test_sentry_init_passes_the_scrubber_and_disables_pii(monkeypatch):
    from sdk import monitoring
    seen = {}
    fake = types.SimpleNamespace(init=lambda **kw: seen.update(kw))
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake)
    monkeypatch.setattr(monitoring, "_initialised", False)
    monkeypatch.setenv("SENTRY_DSN", "https://k@example.ingest.sentry.io/1")
    assert monitoring.init_sentry() is True
    assert seen["send_default_pii"] is False and seen["before_send"] is monitoring.scrub_event
    monkeypatch.setattr(monitoring, "_initialised", False)


def test_the_scrubber_drops_bodies_and_credentials_and_redacts_secrets_in_strings():
    from sdk.monitoring import scrub_event
    event = {
        "request": {"url": "https://e.test/x", "data": {"app_password": "abcd efgh"}, "cookies": {"console_session": "v1.x"},
                    "query_string": "secret=hunter2",
                    "headers": {"Authorization": "Bearer abc", "X-Site-Key": "cfte_zzz", "Accept": "json"}},
        "exception": {"values": [{"value": "failed https://u:pw@db.example/x?apikey=SUPERSECRETKEY123"}]},
    }
    out = scrub_event(event)
    assert "data" not in out["request"] and "cookies" not in out["request"] and "query_string" not in out["request"]
    assert out["request"]["headers"]["Authorization"] == "[Filtered]" and out["request"]["headers"]["X-Site-Key"] == "[Filtered]"
    assert out["request"]["headers"]["Accept"] == "json"
    flat = str(out)
    assert "SUPERSECRETKEY123" not in flat and "pw@" not in flat


# ------------------------------------------------------------------ backups
def test_sqlite_backup_is_a_consistent_copy_and_old_ones_are_pruned(tmp_path, monkeypatch):
    db = tmp_path / "live.db"
    con = sqlite3.connect(db)
    con.execute("create table t (v text)")
    con.execute("insert into t values ('kept')")
    con.commit()
    con.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db.as_posix()}")
    from scripts import backup_db
    out_dir = tmp_path / "bk"
    first = backup_db.run(str(out_dir), keep=2)
    copy = sqlite3.connect(first["file"])
    assert copy.execute("select v from t").fetchall() == [("kept",)]
    copy.close()
    import time
    for _ in range(3):
        time.sleep(0.01)
        (out_dir / f"contentfte-fake{_}.sqlite3").write_bytes(b"x")
    res = backup_db.run(str(out_dir), keep=2)
    assert len(list(out_dir.glob("contentfte-*"))) == 2 and res["pruned"]


def test_backup_of_a_missing_sqlite_file_fails_loudly(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'nope.db').as_posix()}")
    from scripts import backup_db
    with pytest.raises(FileNotFoundError):
        backup_db.run(str(tmp_path / "bk"))


# ------------------------------------------------------------------ alerts
@pytest.fixture
def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'ops.db'}")
    monkeypatch.setenv("SDK_MASTER_KEY", "k")
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


def test_no_alerts_when_everything_is_fine(svc):
    from sdk.ops import collect_alerts, format_alerts
    svc.upsert_site("calm", "Calm", "custom", "https://calm.test", {"posting_frequency": "manual"})
    alerts = collect_alerts()
    assert not [a for a in alerts if a["site"] == "calm"]
    assert format_alerts([]) == ""


def test_budget_and_overdue_alerts_name_the_site(svc):
    from lib.db import Article, CostLedger, Site, get_session
    from sdk.ops import collect_alerts, format_alerts
    svc.upsert_site("busy", "Busy", "custom", "https://busy.test",
                    {"posting_frequency": "daily", "budget": {"monthly_usd": 10}})
    aid = svc.submit_article("busy", keyword="old post")["id"]
    s = get_session()
    try:
        site = s.query(Site).filter_by(slug="busy").one()
        art = s.get(Article, aid)
        art.status = "published"
        art.published_at = datetime.now(timezone.utc) - timedelta(days=10)
        s.add(CostLedger(site_id=site.id, article_id=aid, kind="text", amount_usd=9.5))
        s.commit()
    finally:
        s.close()
    got = {a["code"] for a in collect_alerts() if a["site"] == "busy"}
    assert got == {"budget_warning", "cadence_overdue"}
    s = get_session()
    try:
        s.add(CostLedger(site_id=s.query(Site).filter_by(slug="busy").one().id, article_id=aid, kind="text", amount_usd=1.0))
        s.commit()
    finally:
        s.close()
    codes = {a["code"] for a in collect_alerts() if a["site"] == "busy"}
    assert "budget_exceeded" in codes and "budget_warning" not in codes
    assert "budget_exceeded" in format_alerts([a for a in collect_alerts() if a["site"] == "busy"])


def test_the_alert_script_posts_once_and_never_leaks_the_webhook(svc, monkeypatch):
    from scripts import alerts_check
    monkeypatch.setattr(alerts_check, "collect_alerts",
                        lambda: [{"severity": "critical", "code": "not_ready", "site": "", "message": "db down"}])
    posted = []
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.test/api/webhooks/123/SECRETTOKEN")
    out = alerts_check.run(post=lambda url, body: posted.append((url, body)) or types.SimpleNamespace(ok=True))
    assert out["posted"] is True and len(posted) == 1 and "not_ready" in posted[0][1]
    assert alerts_check.run(dry_run=True, post=lambda *a: pytest.fail("dry run must not post"))["posted"] is False

    def boom(url, body):
        raise RuntimeError("connection to https://discord.test/api/webhooks/123/SECRETTOKEN failed")

    assert alerts_check.run(post=boom)["posted"] is False             # swallowed, not re-raised with the URL


def test_the_audit_actor_is_blank_for_a_cli_job_outside_a_request(svc):
    from lib.actor import current_actor
    assert current_actor() == ""
