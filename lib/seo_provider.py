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
from datetime import datetime, timedelta, timezone

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from lib.db import SeoCache

CACHE_DAYS = 30


def provider_name() -> str:
    return (os.environ.get("SEO_DATA_PROVIDER") or "off").strip().lower()


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
        "difficulty": float(payload.get("difficulty", 0) or 0),
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
        "difficulty": float(first.get("competition", 0) or 0),
        "intent": str(first.get("intent", "informational")),
        "serp": [],
        "serp_gaps": [],
        "raw_tasks": len(tasks),
    }


def get_keyword_data(session: Session, keyword: str, manual: dict | None = None) -> dict:
    """Main entry. `manual` supplies the off-mode fields when provider=off."""
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
    cached = _cache_get(session, provider, keyword)
    if cached is not None:
        return {**cached, "cache_hit": True}
    if provider == "openseo":
        data = _openseo_fetch(keyword)
    elif provider == "dataforseo":
        data = _dataforseo_fetch(keyword)
    else:
        raise ValueError(f"unknown SEO_DATA_PROVIDER: {provider}")
    data["cache_hit"] = False
    _cache_set(session, provider, keyword, data)
    return data
