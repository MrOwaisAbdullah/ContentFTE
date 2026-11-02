"""§5.14 SEO data engine — provider abstraction.

SEO_DATA_PROVIDER env: `openseo` | `dataforseo` | `off` (default: off).

- `off`: manual keyword/SEO data entry, zero data cost (bootstrap mode).
- `openseo`: hosted $10/mo API (default when provider is on).
- `dataforseo`: direct API, Sandbox mock for build/test.

Cached 30 days per keyword in Postgres (lib.db.SeoCache).
No LLM calls — safe to use without touching the model router.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from lib.db import SeoCache

CACHE_DAYS = 30


def provider_name() -> str:
    return (os.environ.get("SEO_DATA_PROVIDER") or "off").strip().lower()


_SITE_KEY = re.compile(r"^s(\d+):(.*)$", re.S)


def cache_key(keyword: str, site_id: int | None = None) -> str:
    """The `seo_cache.keyword` value for a keyword on a site (TEN-07).

    The cache row also holds the SERP snapshot the monthly drift job compares against, so two tenants sharing
    a keyword shared ONE baseline - tenant B's refresh silently replaced tenant A's, and each saw the other's
    drift. The site goes into the key itself (no schema change: a new column would not reach an existing
    database without a migration). Rows written before this, and calls with no site, keep the bare keyword."""
    return f"s{int(site_id)}:{keyword}" if site_id else keyword


def split_cache_key(key: str) -> tuple[int | None, str]:
    """Inverse of `cache_key`: (site_id | None, keyword)."""
    m = _SITE_KEY.match(key or "")
    return (int(m.group(1)), m.group(2)) if m else (None, key or "")


BASELINE_PREFIX = "base:"


def baseline_key(ckey: str) -> str:
    """The cache row that holds a keyword's SERP BASELINE (SEO-17).

    The 30-day cache row is overwritten every time it expires, and the drift job compared "fresh" against whatever
    that row held - so after an expiry the baseline had silently moved forward and a real change in the results was
    never seen. The baseline now lives in its own row, written once (the first SERP seen for the keyword) and moved
    only deliberately, by `set_baseline`."""
    return BASELINE_PREFIX + ckey


def get_baseline(session: Session, provider: str, ckey: str) -> dict | None:
    row = session.execute(
        select(SeoCache).where(SeoCache.provider == provider, SeoCache.keyword == baseline_key(ckey))
    ).scalar_one_or_none()
    return dict(row.data or {}) if row is not None else None


def set_baseline(session: Session, provider: str, ckey: str, data: dict) -> None:
    """Write (or deliberately replace) the baseline snapshot for a keyword."""
    key = baseline_key(ckey)
    row = session.execute(
        select(SeoCache).where(SeoCache.provider == provider, SeoCache.keyword == key)
    ).scalar_one_or_none()
    snapshot = {k: data.get(k) for k in ("serp", "serp_gaps", "volume", "difficulty", "intent") if k in data}
    if row is None:
        session.add(SeoCache(provider=provider, keyword=key, data=snapshot))
    else:
        row.data = snapshot
        row.fetched_at = datetime.now(timezone.utc)
    session.commit()


def _cache_get(session: Session, provider: str, keyword: str) -> dict | None:
    row = session.execute(
        select(SeoCache).where(SeoCache.provider == provider, SeoCache.keyword == keyword)
    ).scalar_one_or_none()
    if row is None:
        return None
    age = datetime.now(timezone.utc) - row.fetched_at.replace(tzinfo=timezone.utc)
    if age > timedelta(days=CACHE_DAYS):
        return None
    return dict(row.data or {})


def _cache_set(session: Session, provider: str, keyword: str, data: dict) -> None:
    row = session.execute(
        select(SeoCache).where(SeoCache.provider == provider, SeoCache.keyword == keyword)
    ).scalar_one_or_none()
    if row is None:
        row = SeoCache(provider=provider, keyword=keyword, data=data)
        session.add(row)
    else:
        row.data = data
        row.fetched_at = datetime.now(timezone.utc)
    session.commit()


def manual_keyword_data(
    keyword: str,
    volume: int = 0,
    difficulty: float = 0.0,
    intent: str = "informational",
    serp_notes: str = "",
) -> dict:
    """`off` mode — operator-entered fields per brief. Zero data cost."""
    return {
        "provider": "off",
        "keyword": keyword,
        "volume": volume,
        "difficulty": difficulty,
        "intent": intent,
        "serp": [],
        "serp_gaps": [],
        "manual_notes": serp_notes,
    }


def normalize_difficulty(value, *, scale: int = 100) -> float:
    """A difficulty on the 0-100 scale the ledger's priority score expects (SEO-15).

    Providers disagree: OpenSEO already answers 0-100, DataForSEO's `competition` is 0-1. Mixing them made a
    DataForSEO keyword look ~100x easier than the same keyword from OpenSEO and skewed `priority_score`.
    `scale=1` means "the provider speaks 0-1"; the result is clamped to 0-100 either way."""
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    if scale == 1:
        v *= 100.0
    return round(max(0.0, min(100.0, v)), 2)


def _openseo_fetch(keyword: str) -> dict:
    base = (os.environ.get("OPENSEO_API_BASE") or "https://api.openseo.so/v1").rstrip("/")
    key = os.environ.get("OPENSEO_API_KEY", "")
    resp = requests.post(
        f"{base}/keyword_research",
        headers={"Authorization": f"Bearer {key}"} if key else {},
        json={"keyword": keyword},
        timeout=20,
    )
    resp.raise_for_status()
    payload = resp.json()
    return {
        "provider": "openseo",
        "keyword": keyword,
        "volume": int(payload.get("volume", 0) or 0),
        "difficulty": normalize_difficulty(payload.get("difficulty")),
        "intent": str(payload.get("intent", "informational")),
        "serp": payload.get("serp", [])[:10],
        "serp_gaps": payload.get("serp_gaps", [])[:3],
        "raw": payload,
    }


def _dataforseo_fetch(keyword: str) -> dict:
    if (os.environ.get("DATAFORSEO_SANDBOX") or "").lower() in {"1", "true", "yes"}:
        return {
            "provider": "dataforseo",
            "keyword": keyword,
            "volume": 1000,
            "difficulty": 25.0,
            "intent": "informational",
            "serp": [],
            "serp_gaps": ["sandbox: gap analysis unavailable"],
            "sandbox": True,
        }
    login = os.environ.get("DATAFORSEO_LOGIN", "")
    password = os.environ.get("DATAFORSEO_PASSWORD", "")
    resp = requests.post(
        "https://api.dataforseo.com/v3/keywords_data/google/search_volume/live",
        auth=(login, password),
        json=[{"keyword": keyword}],
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()
    tasks = (payload.get("tasks") or [{}])[0].get("result") or []
    first = tasks[0] if tasks else {}
    return {
        "provider": "dataforseo",
        "keyword": keyword,
        "volume": int(first.get("search_volume", 0) or 0),
        # `competition_index` is already 0-100; the plain `competition` is 0-1
        "difficulty": (normalize_difficulty(first["competition_index"])
                       if first.get("competition_index") is not None
                       else normalize_difficulty(first.get("competition"), scale=1)),
        "intent": str(first.get("intent", "informational")),
        "serp": [],
        "serp_gaps": [],
        "raw_tasks": len(tasks),
    }


def get_keyword_data(session: Session, keyword: str, manual: dict | None = None,
                     force_refresh: bool = False, site_id: int | None = None) -> dict:
    """Main entry. `manual` supplies the off-mode fields when provider=off.

    `force_refresh=True` (§5.16 SERP drift job) bypasses the read cache but
    still writes the fresh payload back — the new data becomes the baseline
    the next drift comparison runs against."""
    provider = provider_name()
    keyword = keyword.strip()
    if provider == "off":
        m = manual or {}
        return manual_keyword_data(
            keyword,
            volume=int(m.get("volume", 0) or 0),
            difficulty=float(m.get("difficulty", 0) or 0),
            intent=str(m.get("intent", "informational")),
            serp_notes=str(m.get("serp_notes", "")),
        )
    ckey = cache_key(keyword, site_id)
    cached = None if force_refresh else _cache_get(session, provider, ckey)
    if cached is not None:
        return {**cached, "cache_hit": True}
    if provider == "openseo":
        data = _openseo_fetch(keyword)
    elif provider == "dataforseo":
        data = _dataforseo_fetch(keyword)
    else:
        raise ValueError(f"unknown SEO_DATA_PROVIDER: {provider}")
    data["cache_hit"] = False
    _cache_set(session, provider, ckey, data)
    if data.get("serp") and get_baseline(session, provider, ckey) is None:
        set_baseline(session, provider, ckey, data)        # first SERP we ever saw for this keyword = the baseline
    return data
