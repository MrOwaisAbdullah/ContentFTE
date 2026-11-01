"""Per-site API keys (plan SEC-03).

Until now one shared `SDK_MASTER_KEY` opened every site: a key given to one client's website could
read, approve, publish or delete any other client's articles. A site key is bound to exactly one
site and a set of scopes, is stored only as a SHA-256 hash (the plaintext is returned once, at
creation), and can be revoked without touching anyone else.

Scopes (a key must carry the scope a route needs; `admin` implies every scope, and any scope
implies `read`):
    read     GET the site's articles, content, queue, health, sitemap/llms.txt
    write    submit keywords/briefs, generate, edit content/meta, stage images
    approve  approve / reopen articles (subject to the quality gate)
    publish  publish and refresh articles on the live site
    admin    delete articles/keywords, and everything above

The master key (SDK_MASTER_KEY) stays the *platform* credential: it can reach every site and the
platform-wide routes (site create/delete, logs, stage runs, key management). Site keys are for
clients and their websites; they never see other tenants and are not accepted on `/mcp`.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from sqlalchemy import select

from lib.db import ApiKey, AuditLog, Site, get_session, init_db

KEY_PREFIX = "cfte_"
SCOPES = ("read", "write", "approve", "publish", "admin")
DEFAULT_SCOPES = ("read",)          # least privilege: a client site that only renders content
_TOUCH_EVERY = timedelta(minutes=5)  # don't write last_used_at on every request


def _err(message: str, nxt: str = "") -> dict:
    return {"error": message, **({"next": nxt} if nxt else {})}


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return (dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt).isoformat()


def hash_key(key: str) -> str:
    return hashlib.sha256((key or "").encode("utf-8")).hexdigest()


def generate_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def looks_like_site_key(value: Optional[str]) -> bool:
    return bool(value) and str(value).startswith(KEY_PREFIX)


def normalize_scopes(scopes: Optional[Iterable[str]]) -> tuple[list[str], list[str]]:
    """-> (valid scopes in canonical order, unknown scopes). Empty input means the default."""
    asked = [str(s).strip().lower() for s in (scopes or []) if str(s).strip()]
    if not asked:
        return list(DEFAULT_SCOPES), []
    unknown = [s for s in asked if s not in SCOPES]
    return [s for s in SCOPES if s in asked], unknown


def _public(row: ApiKey) -> dict:
    return {"id": row.id, "prefix": row.prefix, "label": row.label, "scopes": list(row.scopes or []),
            "created_at": _iso(row.created_at), "last_used_at": _iso(row.last_used_at),
            "revoked_at": _iso(row.revoked_at), "active": row.revoked_at is None}


def create_site_key(site_slug: str, label: str = "", scopes: Optional[Iterable[str]] = None,
                    via: str = "api") -> dict:
    """Mint a key for one site. The returned `key` is the ONLY time the plaintext exists."""
    init_db()
    s = get_session()
    try:
        site = s.execute(select(Site).where(Site.slug == site_slug)).scalar_one_or_none()
        if site is None:
            return _err(f"site '{site_slug}' not found", "run list_sites for valid slugs")
        valid, unknown = normalize_scopes(scopes)
        if unknown:
            return _err(f"unknown scope(s): {', '.join(unknown)}", f"use any of: {', '.join(SCOPES)}")
        key = generate_key()
        row = ApiKey(site_id=site.id, key_hash=hash_key(key), prefix=key[:12],
                     label=(label or "").strip()[:120], scopes=valid)
        s.add(row)
        s.add(AuditLog(site_id=site.id, action="key.create",
                       payload={"prefix": row.prefix, "label": row.label, "scopes": valid, "via": via}))
        s.commit()
        s.refresh(row)
        return {**_public(row), "key": key, "site": site.slug,
                "note": "Store this key now — it is shown only once and cannot be recovered."}
    finally:
        s.close()


def list_site_keys(site_slug: str) -> dict:
    """Keys for a site, newest first. Never includes the hash or the plaintext."""
    init_db()
    s = get_session()
    try:
        site = s.execute(select(Site).where(Site.slug == site_slug)).scalar_one_or_none()
        if site is None:
            return _err(f"site '{site_slug}' not found", "run list_sites for valid slugs")
        rows = s.execute(select(ApiKey).where(ApiKey.site_id == site.id)
                         .order_by(ApiKey.id.desc())).scalars().all()
        return {"site": site.slug, "keys": [_public(r) for r in rows],
                "active": sum(1 for r in rows if r.revoked_at is None)}
    finally:
        s.close()


def revoke_site_key(site_slug: str, key_id: int, via: str = "api") -> dict:
    init_db()
    s = get_session()
    try:
        site = s.execute(select(Site).where(Site.slug == site_slug)).scalar_one_or_none()
        if site is None:
            return _err(f"site '{site_slug}' not found", "run list_sites for valid slugs")
        row = s.get(ApiKey, key_id)
        if row is None or row.site_id != site.id:   # a key id from another site is "not found"
            return _err(f"key {key_id} not found on site '{site_slug}'", "list the site's keys first")
        if row.revoked_at is None:
            row.revoked_at = datetime.now(timezone.utc)
            s.add(AuditLog(site_id=site.id, action="key.revoke",
                           payload={"prefix": row.prefix, "label": row.label, "via": via}))
            s.commit()
        return {"revoked": True, **_public(row)}
    finally:
        s.close()


def lookup(provided: Optional[str]) -> Optional[dict]:
    """Resolve a presented key to {key_id, site_id, site_slug, scopes, label}, or None.

    Only active (non-revoked) keys resolve. The lookup is one indexed equality on the hash, so there
    is no per-character timing signal to exploit; `last_used_at` is refreshed at most every 5 minutes."""
    if not looks_like_site_key(provided):
        return None
    init_db()
    s = get_session()
    try:
        row = s.execute(select(ApiKey).where(ApiKey.key_hash == hash_key(provided))).scalar_one_or_none()
        if row is None or row.revoked_at is not None:
            return None
        now = datetime.now(timezone.utc)
        last = row.last_used_at
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if last is None or now - last > _TOUCH_EVERY:
            row.last_used_at = now
            s.commit()
        return {"key_id": row.id, "site_id": row.site_id, "site_slug": row.site.slug,
                "scopes": list(row.scopes or []), "label": row.label or row.prefix}
    finally:
        s.close()


def active_key_count(session, site_id: int) -> int:
    return len(session.execute(select(ApiKey.id).where(
        ApiKey.site_id == site_id, ApiKey.revoked_at.is_(None))).all())
