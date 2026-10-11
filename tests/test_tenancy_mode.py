"""Tenancy modes + site identity env (docs/spec-site2-postgres-frontend.md §4b).

isolated (default) keeps today's behavior: empty slug falls back to
DEFAULT_SITE_SLUG. shared (SaaS shape, platform DB) refuses that fallback so a
misconfigured process can never write into another tenant's data.
"""
import importlib
import importlib.util
import os
import sys

import pytest
from sqlalchemy import select

from lib import site_env
from lib import store

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_provision_tenant():
    path = os.path.join(REPO_ROOT, "scripts", "provision_tenant.py")
    spec = importlib.util.spec_from_file_location("provision_tenant_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def temp_db(tmp_path):
    import lib.db as db
    old_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path / 'tenancy_test.db'}"
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


# ---------------------------------------------------------------------------
# site_env: mode + identity parsing
# ---------------------------------------------------------------------------
def test_tenancy_mode_defaults_to_isolated(monkeypatch):
    monkeypatch.delenv("TENANCY_MODE", raising=False)
    assert site_env.tenancy_mode() == "isolated"
    assert site_env.is_shared_mode() is False


def test_tenancy_mode_shared(monkeypatch):
    monkeypatch.setenv("TENANCY_MODE", "shared")
    assert site_env.is_shared_mode() is True


def test_site_identity_defaults_are_site_one():
    # import-time snapshot; defaults must equal site #1 until env overrides
    importlib.reload(site_env)
    assert site_env.SITE_BASE_URL == "https://owaisabdullah.dev"
    assert site_env.SITE_HOST == "owaisabdullah.dev"
    assert site_env.SITE_PREFIX == "https://owaisabdullah.dev/blog/"
    assert site_env.SITE_URL == "https://owaisabdullah.dev/"
    assert site_env.AUTHOR_PROFILE_API_URL == "https://owaisabdullah.dev/api/profile"


def test_site_base_url_env_override(monkeypatch):
    monkeypatch.setenv("SITE_BASE_URL", "https://tenant-b.example/")
    importlib.reload(site_env)
    try:
        assert site_env.SITE_BASE_URL == "https://tenant-b.example"
        assert site_env.SITE_HOST == "tenant-b.example"
        assert site_env.SITE_PREFIX == "https://tenant-b.example/blog/"
        assert site_env.SITE_URL == "https://tenant-b.example/"
        assert site_env.AUTHOR_PROFILE_API_URL == "https://tenant-b.example/api/profile"
    finally:
        monkeypatch.delenv("SITE_BASE_URL", raising=False)
        importlib.reload(site_env)


def test_approval_channel_ids_single_and_comma(monkeypatch):
    monkeypatch.delenv("DISCORD_APPROVAL_CHANNEL_IDS", raising=False)
    monkeypatch.delenv("DISCORD_APPROVAL_CHANNEL_ID", raising=False)
    assert site_env.approval_channel_ids() == []
    monkeypatch.setenv("DISCORD_APPROVAL_CHANNEL_ID", "111")
    assert site_env.approval_channel_ids() == [111]
    monkeypatch.setenv("DISCORD_APPROVAL_CHANNEL_IDS", "111, 222, not-a-number")
    assert site_env.approval_channel_ids() == [111, 222]


# ---------------------------------------------------------------------------
# store: default fallback vs shared-mode refusal
# ---------------------------------------------------------------------------
def test_isolated_mode_falls_back_to_default_tenant(temp_db, monkeypatch):
    monkeypatch.delenv("TENANCY_MODE", raising=False)
    session = temp_db.get_session()
    try:
        site = store.get_or_create_site(session, "")
        assert site.slug == store.DEFAULT_SITE_SLUG
    finally:
        session.close()


def test_shared_mode_refuses_empty_slug(temp_db, monkeypatch):
    monkeypatch.setenv("TENANCY_MODE", "shared")
    session = temp_db.get_session()
    try:
        with pytest.raises(ValueError, match="explicit site_slug"):
            store.get_or_create_site(session, "")
    finally:
        session.close()


def test_shared_mode_creates_only_the_explicit_tenant(temp_db, monkeypatch):
    monkeypatch.setenv("TENANCY_MODE", "shared")
    session = temp_db.get_session()
    try:
        site = store.get_or_create_site(session, "tenant-b")
        assert site.slug == "tenant-b"
        rows = session.execute(select(store.Site)).scalars().all()
        assert [r.slug for r in rows] == ["tenant-b"]
    finally:
        session.close()


# ---------------------------------------------------------------------------
# provision_tenant --mode shared
# ---------------------------------------------------------------------------
def test_provision_tenant_shared_creates_site_and_profile(temp_db, monkeypatch, capsys):
    monkeypatch.setenv("TENANCY_MODE", "shared")
    monkeypatch.setattr(sys, "argv", [
        "provision_tenant.py", "--mode", "shared",
        "--slug", "tenant-c", "--name", "Tenant C",
        "--site-type", "wordpress", "--site-url", "https://tenant-c.example",
    ])
    provision_tenant = _load_provision_tenant()
    provision_tenant.main()
    out = capsys.readouterr().out
    assert "Shared tenant provisioned" in out
    assert "TENANCY_MODE=shared" in out
    assert "DEFAULT_SITE_SLUG=tenant-c" in out
    session = temp_db.get_session()
    try:
        site = session.execute(
            select(store.Site).where(store.Site.slug == "tenant-c")).scalar_one()
        assert site.site_type == "wordpress"
        assert site.base_url == "https://tenant-c.example"
    finally:
        session.close()


def test_provision_tenant_isolated_prints_checklist(capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", [
        "provision_tenant.py", "--mode", "isolated", "--slug", "tenant-d"])
    provision_tenant = _load_provision_tenant()
    provision_tenant.main()
    out = capsys.readouterr().out
    assert "Isolated instance checklist" in out
    assert "tenant-d" in out
