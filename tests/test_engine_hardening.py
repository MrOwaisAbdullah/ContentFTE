"""Regression tests for the engine fixes in docs/improvement-plan-2026-11.md:

SEC-04  list_sites / MCP never return stored secrets (only `secrets_set` flags)
CON-04  upsert_site merges settings per group; blank secret = keep, None = remove
TEN-01  shared mode never falls back to process WP_* env
SEC-08  site_health authenticates with the SITE's credentials, not process env
ENG-02  every spelling of "go live" is live (REST said `publish`, connector wanted `auto`)
ENG-05  REST and MCP share one stage single-flight registry
ENG-11  delete_site clears every FK-bound table
PIPE-01 the fact-check tool is registered under the name the prompts use
ADP-13  lib/gbp.py compiles/imports
"""
from __future__ import annotations

import os

import pytest

from lib.secrets_redact import merge_settings, redact_settings

SECRET_WP = "abcd efgh ijkl mnop"
SECRET_HOOK = "https://discord.com/api/webhooks/123/tokentokentoken"

FULL_SETTINGS = {
    "posting_frequency": "daily",
    "wp": {"base_url": "https://x.test", "username": "editor", "app_password": SECRET_WP},
    "indexing": {"indexnow_key": "k-indexnow", "bing_wmt_key": "k-bing", "auto_index_on_publish": True},
    "notifications": {"discord_webhook_url": SECRET_HOOK, "notify_on_publish": True},
    "image": {"vlm_model": "qwen", "max_tokens": 512, "provider_api_key": "sk-live-123"},
}


# --------------------------------------------------------------------------- pure
def test_redact_settings_strips_secrets_and_flags_them():
    safe, flags = redact_settings(FULL_SETTINGS)
    blob = repr(safe)
    for secret in (SECRET_WP, SECRET_HOOK, "k-indexnow", "k-bing", "sk-live-123"):
        assert secret not in blob
    assert safe["wp"]["username"] == "editor"                 # non-secret survives
    assert safe["image"]["max_tokens"] == 512                  # numeric config survives
    assert flags == {"wp_app_password": True, "indexnow_key": True,
                     "bing_wmt_key": True, "discord_webhook_url": True}
    assert FULL_SETTINGS["wp"]["app_password"] == SECRET_WP   # input not mutated


def test_redact_settings_handles_missing_and_blank():
    assert redact_settings(None) == ({}, {"wp_app_password": False, "indexnow_key": False,
                                          "bing_wmt_key": False, "discord_webhook_url": False})
    _, flags = redact_settings({"wp": {"app_password": "   "}})
    assert flags["wp_app_password"] is False


def test_merge_settings_keeps_secret_on_partial_group_save():
    out = merge_settings(FULL_SETTINGS, {"wp": {"username": "new-user"}})
    assert out["wp"] == {"base_url": "https://x.test", "username": "new-user",
                         "app_password": SECRET_WP}


def test_merge_settings_blank_secret_keeps_none_removes_value_replaces():
    kept = merge_settings(FULL_SETTINGS, {"wp": {"app_password": ""}})
    assert kept["wp"]["app_password"] == SECRET_WP
    removed = merge_settings(FULL_SETTINGS, {"wp": {"app_password": None}})
    assert "app_password" not in removed["wp"] and removed["wp"]["username"] == "editor"
    replaced = merge_settings(FULL_SETTINGS, {"wp": {"app_password": "fresh"}})
    assert replaced["wp"]["app_password"] == "fresh"
    # other groups and scalars untouched; input not mutated
    assert replaced["indexing"] == FULL_SETTINGS["indexing"]
    assert FULL_SETTINGS["wp"]["app_password"] == SECRET_WP


def test_merge_settings_scalars_and_new_groups():
    out = merge_settings({"a": 1}, {"a": 2, "new": {"x": 1}, "gone": None})
    assert out == {"a": 2, "new": {"x": 1}}


# --------------------------------------------------------------------------- DB-backed
@pytest.fixture
def engine_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'hardening.db'}")
    monkeypatch.delenv("WP_BASE_URL", raising=False)
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


def test_list_sites_never_returns_secrets(engine_db):
    service = engine_db
    service.upsert_site("s1", "S1", "wordpress", "https://x.test", FULL_SETTINGS)
    row = next(r for r in service.list_sites()["sites"] if r["slug"] == "s1")
    assert row["secrets_set"]["wp_app_password"] is True
    blob = repr(row)
    assert SECRET_WP not in blob and SECRET_HOOK not in blob and "sk-live-123" not in blob
    assert row["settings"]["wp"]["username"] == "editor"
    # ...but the engine itself still holds them for publishing
    from lib.db import Site, get_session
    s = get_session()
    try:
        stored = s.query(Site).filter_by(slug="s1").one()
        assert stored.settings["wp"]["app_password"] == SECRET_WP
    finally:
        s.close()


def test_upsert_site_partial_wp_group_keeps_stored_password(engine_db):
    service = engine_db
    service.upsert_site("s2", "S2", "wordpress", "https://x.test", FULL_SETTINGS)
    service.upsert_site("s2", settings={"wp": {"username": "other", "app_password": ""}})
    from lib.db import Site, get_session
    s = get_session()
    try:
        wp = s.query(Site).filter_by(slug="s2").one().settings["wp"]
        assert wp["username"] == "other" and wp["app_password"] == SECRET_WP
    finally:
        s.close()


def test_shared_mode_never_falls_back_to_process_wp_env(engine_db, monkeypatch):
    monkeypatch.setenv("WP_BASE_URL", "https://tenant-a.example")
    monkeypatch.setenv("WP_USERNAME", "a")
    monkeypatch.setenv("WP_APP_PASSWORD", "a-secret")
    from sdk.service import _wp_config

    class _Site:  # a tenant with no WordPress settings of its own
        settings = {}

    monkeypatch.setenv("TENANCY_MODE", "isolated")
    assert _wp_config(_Site()).base_url == "https://tenant-a.example"      # single-site: env is fine
    monkeypatch.setenv("TENANCY_MODE", "shared")
    cfg = _wp_config(_Site())
    assert (cfg.base_url, cfg.username, cfg.app_password) == ("", "", "")  # tenant B gets nothing
    own = _wp_config(type("S", (), {"settings": {"wp": {
        "base_url": "https://b.example", "username": "b", "app_password": "b-secret"}}})())
    assert own.base_url == "https://b.example" and own.app_password == "b-secret"


def test_site_health_uses_the_sites_own_wordpress_credentials(engine_db, monkeypatch):
    service = engine_db
    monkeypatch.setenv("WP_BASE_URL", "https://tenant-a.example")
    monkeypatch.setenv("WP_USERNAME", "env-user")
    monkeypatch.setenv("WP_APP_PASSWORD", "env-secret")
    monkeypatch.setenv("TENANCY_MODE", "shared")
    service.upsert_site("tenant-b", "B", "wordpress", "https://b.example",
                        {"wp": {"base_url": "https://b.example", "username": "b-user",
                                "app_password": "b-secret"}})
    seen = []

    class _Resp:
        status_code = 200

        def json(self):
            return {"blog_public": 1}

    def fake_get(url, timeout=5, auth=None, **_):
        seen.append((url, auth))
        return _Resp()

    out = service.site_health("tenant-b", http_get=fake_get)
    wp_calls = [c for c in seen if "/wp-json/wp/v2/settings" in c[0]]
    assert wp_calls, out
    assert all(auth == ("b-user", "b-secret") for _, auth in wp_calls)       # never env-user/env-secret
    assert not any("env-secret" in repr(c) for c in seen)


def test_every_live_spelling_is_live():
    from lib.wordpress import is_live_mode
    for live in ("auto", "publish", "live", "PUBLISH", " Auto "):
        assert is_live_mode(live) is True
    for draft in ("draft", "", None, "preview"):
        assert is_live_mode(draft) is False


def test_rest_and_mcp_share_one_stage_registry():
    import mcp_server.server as mcp_mod
    import sdk.server as rest_mod
    assert mcp_mod._running_stages is rest_mod._running_stages
    assert mcp_mod._stage_lock is rest_mod._run_lock


def test_delete_site_clears_every_fk_table(engine_db):
    service = engine_db
    from lib.db import AuditLog, BrandProfile, ShareOfVoice, Site, TavilyUsage, get_session
    service.upsert_site("gone", "Gone", "wordpress", "https://g.test")
    s = get_session()
    try:
        sid = s.query(Site).filter_by(slug="gone").one().id
        s.add_all([
            BrandProfile(site_id=sid, profile={"voice": "plain"}),
            ShareOfVoice(site_id=sid, month="2026-11", platform="chatgpt", prompt="p", cited=False),
            TavilyUsage(site_id=sid, month="2026-11", calls=3),
        ])
        s.commit()
    finally:
        s.close()
    assert service.delete_site("gone") == {"deleted": "gone", "id": sid}
    s = get_session()
    try:
        assert s.query(Site).filter_by(slug="gone").count() == 0
        for model in (BrandProfile, ShareOfVoice, TavilyUsage):
            assert s.query(model).filter_by(site_id=sid).count() == 0
        assert s.query(AuditLog).filter_by(action="site.deleted").count() == 1
    finally:
        s.close()


def test_factcheck_tool_is_registered_under_the_prompt_name():
    from tools.factcheck_tool import factcheck_gate_tool
    assert factcheck_gate_tool.name == "factcheck_gate_tool"


def test_gbp_module_imports_and_parses_hours():
    import lib.gbp as gbp
    assert gbp._HOURS_RE.search("Opening hours: 09:00 - 17:30").group(1) == "09:00 - 17:30"
    assert "absent" in gbp._compare_field(None, "x", "phone")["message"]
