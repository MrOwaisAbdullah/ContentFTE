"""Plan SEO-05 / SEO-14: max_posts_per_cadence is a real sliding-window cap, enforcement is a
per-site setting, and the stale-year check follows the calendar."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

NOW = datetime.now(timezone.utc)


@pytest.fixture
def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'cadence.db'}")
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


def _site(svc, **settings):
    svc.upsert_site("cad", "Cadence", "custom", "https://cad.test",
                    {"require_approval": False, **settings})


def _publish_at(svc, hours_ago: float, title="p"):
    """An already-published article, published `hours_ago` ago."""
    from lib.db import Article, get_session
    art = svc.submit_article("cad", keyword=f"{title}-{hours_ago}")
    s = get_session()
    try:
        a = s.get(Article, art["id"])
        a.status = "published"
        a.content_md = "body"
        a.published_at = NOW - timedelta(hours=hours_ago)
        s.commit()
    finally:
        s.close()


def _cadence(svc):
    return svc.site_cadence("cad")["cadence"]


def _approved(svc, kw="next"):
    from lib.db import Article, get_session
    art = svc.submit_article("cad", keyword=kw)
    s = get_session()
    try:
        a = s.get(Article, art["id"])
        a.status, a.content_md = "approved", "body"
        s.commit()
    finally:
        s.close()
    return art["id"]


def test_cap_of_one_behaves_like_before(svc):
    _site(svc, posting_frequency="daily", max_posts_per_cadence=1)
    assert _cadence(svc)["can_publish_now"] is True
    _publish_at(svc, 2)
    c = _cadence(svc)
    assert c["can_publish_now"] is False and c["posts_in_window"] == 1
    assert 21 * 3600 < c["seconds_remaining"] < 23 * 3600


def test_cap_greater_than_one_allows_that_many_per_window(svc):
    _site(svc, posting_frequency="daily", max_posts_per_cadence=3)
    _publish_at(svc, 5, "a")
    _publish_at(svc, 3, "b")
    assert _cadence(svc)["can_publish_now"] is True            # 2 of 3 used
    _publish_at(svc, 1, "c")
    c = _cadence(svc)
    assert c["can_publish_now"] is False and c["posts_in_window"] == 3
    # the slot opens when the OLDEST counted post (5h ago) leaves the 24h window -> ~19h from now
    assert 18 * 3600 < c["seconds_remaining"] < 20 * 3600


def test_posts_outside_the_window_do_not_count(svc):
    _site(svc, posting_frequency="daily", max_posts_per_cadence=1)
    _publish_at(svc, 30)                                        # yesterday-ish: outside 24h
    c = _cadence(svc)
    assert c["can_publish_now"] is True and c["posts_in_window"] == 0


def test_manual_cadence_never_blocks_or_auto_publishes(svc):
    _site(svc, posting_frequency="manual", auto_publish=True)
    _publish_at(svc, 1)
    c = _cadence(svc)
    assert c["can_publish_now"] is True and c["can_auto_publish"] is False


def test_publish_is_advisory_by_default_and_blocked_when_the_site_enforces(svc):
    _site(svc, posting_frequency="daily", max_posts_per_cadence=1)
    _publish_at(svc, 1)
    assert svc.publish_article(_approved(svc, "one"))["status"] == "published"   # advisory: goes through

    svc2_slug = "cad"
    svc.upsert_site(svc2_slug, settings={"enforce_cadence": True})
    blocked = svc.publish_article(_approved(svc, "two"))
    assert "error" in blocked and "cadence limit reached" in blocked["error"]
    assert "1 of 1" in blocked["error"] or "of 1 allowed" in blocked["error"]

    forced = svc.publish_article(_approved(svc, "three"), force=True)           # explicit override
    assert forced["status"] == "published"


def test_stale_year_follows_the_calendar():
    from sdk.service import _stale_year_re
    r2026 = _stale_year_re(datetime(2026, 11, 1, tzinfo=timezone.utc))
    assert r2026.search("Best tools in 2025")
    assert not r2026.search("Best tools in 2026")        # current year is not stale
    assert not r2026.search("Best tools in 2027")
    r2027 = _stale_year_re(datetime(2027, 1, 5, tzinfo=timezone.utc))
    assert r2027.search("Best tools in 2026")            # it used to stop at 2025 forever
