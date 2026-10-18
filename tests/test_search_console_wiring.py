"""Per-site Search Console wiring (multi-property, one service account).

Everything Google-side is monkeypatched — offline by construction. Covers:
the property resolver, domain-property matching, the sites.list TTL cache
(cached burst / force bypass / failures never cached), and the service op's
tri-state per-site report.
"""
from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

from lib import search_console


# ---------------------------------------------------------------------------
# Resolver + matcher (pure functions)
# ---------------------------------------------------------------------------
def test_resolve_site_property_prefers_override_then_base_url():
    assert search_console.resolve_site_property("https://a.test", None) == "https://a.test/"
    assert search_console.resolve_site_property("https://a.test/", {}) == "https://a.test/"
    # explicit override wins — URL-prefix or domain property
    assert search_console.resolve_site_property(
        "https://ignored.test", {"search_console_site_url": "sc-domain:x.com"}
    ) == "sc-domain:x.com"
    assert search_console.resolve_site_property(
        "https://ignored.test", {"search_console_site_url": "https://alt.test/"}
    ) == "https://alt.test/"
    # no base_url and no override -> not configured (caller reports, no query)
    assert search_console.resolve_site_property("", None) == ""
    assert search_console.resolve_site_property(None, {}) == ""


def test_match_property_exact_domain_property_and_miss():
    visible = [
        {"site_url": "https://a.test/", "permission_level": "full"},
        {"site_url": "sc-domain:b.test", "permission_level": "restricted"},
    ]
    # exact, trailing slash tolerated
    assert search_console.match_property("https://a.test", visible)["permission_level"] == "full"
    assert search_console.match_property("https://a.test/", visible)["permission_level"] == "full"
    # a domain property covers every URL-prefix property on that host
    assert search_console.match_property("https://b.test/blog/", visible)["site_url"] == "sc-domain:b.test"
    assert search_console.match_property("https://www.b.test/", visible)["site_url"] == "sc-domain:b.test"
    # not visible
    assert search_console.match_property("https://c.test/", visible) is None


# ---------------------------------------------------------------------------
# sites.list cache
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _clean_cache():
    search_console._visible_cache.clear()
    yield
    search_console._visible_cache.clear()


def _fake_sites_get(calls: dict, entries: list):
    def fake_get(url, headers=None, timeout=None):
        calls["n"] += 1
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"siteEntry": entries},
        )
    return fake_get


def test_list_accessible_properties_caches_and_forces(monkeypatch):
    calls = {"n": 0}
    entries = [{"siteUrl": "https://a.test/", "permissionLevel": "restricted"}]
    monkeypatch.setattr(search_console, "_get_access_token", lambda: "tok")
    monkeypatch.setattr(search_console.requests, "get", _fake_sites_get(calls, entries))

    first = search_console.list_accessible_properties(max_age=300)
    second = search_console.list_accessible_properties(max_age=300)
    assert first == second == [
        {"site_url": "https://a.test/", "permission_level": "restricted"}]
    assert calls["n"] == 1  # burst served from cache

    search_console.list_accessible_properties(max_age=300, force=True)
    assert calls["n"] == 2  # force bypasses the cache

    search_console.list_accessible_properties(max_age=0)
    assert calls["n"] == 3  # max_age=0 always refreshes


def test_list_accessible_properties_failures_are_not_cached(monkeypatch):
    calls = {"n": 0}

    def boom(*a, **k):
        calls["n"] += 1
        raise RuntimeError("api down")

    monkeypatch.setattr(search_console, "_get_access_token", lambda: "tok")
    monkeypatch.setattr(search_console.requests, "get", boom)
    assert search_console.list_accessible_properties() is None
    assert search_console.list_accessible_properties() is None
    assert calls["n"] == 2  # a failure never poisons the cache


def test_credentials_fingerprint_separates_instances(monkeypatch):
    """Two instances' GOOGLE_CREDENTIALS never share a cache slot."""
    monkeypatch.setenv("GOOGLE_CREDENTIALS", '{"client_email": "a@x"}')
    fp_a = search_console._creds_fingerprint()
    monkeypatch.setenv("GOOGLE_CREDENTIALS", '{"client_email": "b@x"}')
    fp_b = search_console._creds_fingerprint()
    assert fp_a != fp_b
    monkeypatch.setenv("GOOGLE_CREDENTIALS", '{"client_email": "a@x"}')
    assert search_console._creds_fingerprint() == fp_a


def test_list_accessible_properties_cache_is_per_credential(monkeypatch):
    calls = {"n": 0}
    entries = [{"siteUrl": "https://a.test/", "permissionLevel": "full"}]
    monkeypatch.setattr(search_console, "_get_access_token", lambda: "tok")
    monkeypatch.setattr(search_console.requests, "get",
                        _fake_sites_get(calls, entries))

    monkeypatch.setenv("GOOGLE_CREDENTIALS", '{"client_email": "a@x"}')
    assert search_console.list_accessible_properties() is not None
    assert search_console.list_accessible_properties() is not None
    assert calls["n"] == 1                      # same creds -> cached
    monkeypatch.setenv("GOOGLE_CREDENTIALS", '{"client_email": "b@x"}')
    assert search_console.list_accessible_properties() is not None
    assert calls["n"] == 2                      # different SA -> own fetch
    monkeypatch.setenv("GOOGLE_CREDENTIALS", '{"client_email": "a@x"}')
    assert search_console.list_accessible_properties() is not None
    assert calls["n"] == 2                      # back to a -> still cached


# ---------------------------------------------------------------------------
# Service op (temp sqlite, monkeypatched Google side)
# ---------------------------------------------------------------------------
@pytest.fixture
def temp_db(tmp_path):
    import lib.db as db
    old_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = f"sqlite:///{(tmp_path / 'gsc.db').as_posix()}"
    db._engine = None
    db._SessionLocal = None
    db.init_db()
    yield db
    if db._engine is not None:
        db._engine.dispose()
    db._engine = None
    db._SessionLocal = None
    if old_url is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = old_url


def _mk_site(slug: str, base: str, settings: dict | None = None) -> None:
    from lib.db import Site, get_session
    s = get_session()
    try:
        s.add(Site(slug=slug, name=slug, base_url=base, settings=settings or {}))
        s.commit()
    finally:
        s.close()


def test_service_status_connected_and_not_shared(temp_db, monkeypatch):
    from sdk import service
    _mk_site("a", "https://a.test")
    _mk_site("b", "https://b.test")
    monkeypatch.setenv(
        "GOOGLE_CREDENTIALS",
        json.dumps({"client_email": "sa@proj.iam.gserviceaccount.com"}))
    monkeypatch.setattr(
        search_console, "list_accessible_properties",
        lambda *a, **k: [{"site_url": "https://a.test/",
                          "permission_level": "restricted"}])

    out = service.get_search_console_status()
    by = {r["slug"]: r for r in out["sites"]}
    assert by["a"]["connected"] is True
    assert by["a"]["permission_level"] == "restricted"
    assert by["b"]["connected"] is False
    assert by["b"]["property"] == "https://b.test/"
    assert out["service_account_email"] == "sa@proj.iam.gserviceaccount.com"
    assert out["credentials"] is True
    assert out["properties_visible"] == 1


def test_service_status_override_and_missing_creds(temp_db, monkeypatch):
    from sdk import service
    _mk_site("c", "https://ignored.test",
             {"search_console_site_url": "sc-domain:c.test"})
    monkeypatch.delenv("GOOGLE_CREDENTIALS", raising=False)

    out = service.get_search_console_status()
    row = out["sites"][0]
    assert row["property"] == "sc-domain:c.test"   # override wins
    assert row["connected"] is False
    assert "GOOGLE_CREDENTIALS" in row["reason"]
    assert out["credentials"] is False
    assert out["properties_visible"] is None


def test_service_status_api_failure_is_unknown_not_disconnected(temp_db, monkeypatch):
    from sdk import service
    _mk_site("d", "https://d.test")
    monkeypatch.setenv(
        "GOOGLE_CREDENTIALS",
        json.dumps({"client_email": "sa@proj.iam.gserviceaccount.com"}))
    monkeypatch.setattr(search_console, "list_accessible_properties",
                        lambda *a, **k: None)

    out = service.get_search_console_status()
    row = out["sites"][0]
    assert row["connected"] is None  # tri-state: unknown, not a false negative
    assert "could not list" in row["reason"]
