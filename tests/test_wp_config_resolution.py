"""Per-site WordPress credentials (sdk.service._wp_config).

Site.settings["wp"] wins over the process WP_* env, so a shared engine can
never push site B's article into site A's WordPress. Offline: no connector
is built, only config resolution.
"""
from __future__ import annotations

from types import SimpleNamespace

from sdk.service import _wp_config


def _site(settings=None):
    return SimpleNamespace(settings=settings or {})


def test_env_fallback_when_no_site_settings(monkeypatch):
    monkeypatch.setenv("WP_BASE_URL", "https://env.example")
    monkeypatch.setenv("WP_USERNAME", "envuser")
    monkeypatch.setenv("WP_APP_PASSWORD", "envpass")
    cfg = _wp_config(_site())
    assert cfg.base_url == "https://env.example"
    assert cfg.username == "envuser"
    assert cfg.app_password == "envpass"


def test_site_settings_win_over_env(monkeypatch):
    monkeypatch.setenv("WP_BASE_URL", "https://env.example")
    monkeypatch.setenv("WP_USERNAME", "envuser")
    monkeypatch.setenv("WP_APP_PASSWORD", "envpass")
    cfg = _wp_config(_site({"wp": {
        "base_url": "https://site-b.example/",
        "username": "buser",
        "app_password": "bpass",
    }}))
    assert cfg.base_url == "https://site-b.example"   # trailing slash stripped
    assert cfg.username == "buser"
    assert cfg.app_password == "bpass"


def test_incomplete_site_settings_fall_back_to_env(monkeypatch):
    monkeypatch.setenv("WP_BASE_URL", "https://env.example")
    monkeypatch.setenv("WP_USERNAME", "envuser")
    monkeypatch.setenv("WP_APP_PASSWORD", "envpass")
    # wp settings without base_url are treated as unconfigured, not half-used
    cfg = _wp_config(_site({"wp": {"username": "only-user"}}))
    assert cfg.base_url == "https://env.example"
    # site with no settings at all -> env
    assert _wp_config(_site(None)).base_url == "https://env.example"
    assert _wp_config(None).base_url == "https://env.example"
