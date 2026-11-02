"""§5.14 SEO-data tool for the Brief Agent.

Wraps `lib.seo_provider.get_keyword_data`: when `SEO_DATA_PROVIDER=off`
(default) it returns the operator-supplied manual fields at zero cost; when a
provider is on it fetches (and 30-day-caches) volume/difficulty/intent/SERP gaps
for the keyword. Pure DB/HTTP, no LLM.
"""
from __future__ import annotations

from typing import Any, Dict

from agents import function_tool

from lib.db import get_session, init_db
from lib.seo_provider import get_keyword_data, provider_name


def _site_id(session, site_slug: str = ""):
    """The site whose cache namespace this call uses (TEN-07). In shared mode a site is REQUIRED (the store
    refuses to guess a tenant); an isolated instance falls back to its default site."""
    from lib.store import get_or_create_site
    return get_or_create_site(session, site_slug).id


def get_keyword_metrics(
    keyword: str,
    volume: int = 0,
    difficulty: float = 0.0,
    intent: str = "informational",
    serp_notes: str = "",
    site_slug: str = "",
) -> Dict[str, Any]:
    """Fetch keyword metrics for a brief (§5.14), falling back to manual fields.

    Args:
        keyword: The keyword/topic.
        volume: Manual monthly search volume (used when provider is `off`).
        difficulty: Manual keyword difficulty 0-100 (used when provider is `off`).
        intent: Manual intent (used when provider is `off`).
        serp_notes: Optional manual SERP notes (used when provider is `off`).
        site_slug: The site this lookup is for (required when the engine serves several tenants).

    Returns:
        {"status": "ok", "provider", "data": {volume, difficulty, intent,
         serp, serp_gaps, cache_hit?}} or {"status": "error", "message"}.
    """
    keyword = (keyword or "").strip()
    if not keyword:
        return {"status": "error", "message": "keyword is required"}
    init_db()
    session = get_session()
    try:
        data = get_keyword_data(
            session, keyword,
            manual={"volume": volume, "difficulty": difficulty,
                    "intent": intent, "serp_notes": serp_notes},
            site_id=_site_id(session, site_slug),
        )
        return {"status": "ok", "provider": provider_name(), "data": data}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        session.close()


get_keyword_metrics_tool = function_tool(
    get_keyword_metrics, name_override="get_keyword_metrics_tool")
