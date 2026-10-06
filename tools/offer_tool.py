"""§5.5 per-site offer catalog — product/service mentions for brief + draft.

Reads `offers` from the site's Brand DNA profile (stored JSON, no schema
change): a list of {"name", "description", "url", "cta"?} entries. Pure DB
read, no LLM. The Brief Agent decides placement (max 2 natural mentions + 1
CTA block); the Content Generator follows the brief and never invents offers.
"""
from __future__ import annotations

from typing import Any, Dict, List

from agents import function_tool
from sqlalchemy import select

from lib.brand_dna import load_profile
from lib.db import Site, get_session, init_db

MAX_MENTIONS = 2
MAX_CTAS = 1


def _clean_offers(raw: Any) -> List[dict]:
    offers: List[dict] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str) and item.strip():
                offers.append({"name": item.strip(), "description": "", "url": ""})
            elif isinstance(item, dict) and item.get("name"):
                offers.append({
                    "name": str(item.get("name", "")).strip(),
                    "description": str(item.get("description", "") or "").strip(),
                    "url": str(item.get("url", "") or "").strip(),
                    "cta": str(item.get("cta", "") or "").strip(),
                })
    return offers


def get_offer_catalog(site_slug: str = "") -> Dict[str, Any]:
    """Return the site's offer catalog (§5.5) for brief placement decisions.

    Args:
        site_slug: Optional site slug; defaults to the first configured site.

    Returns:
        {"status": "ok", "offers": [{name, description, url, cta}], "limits":
         {"max_mentions": 2, "max_ctas": 1}} or
        {"status": "error", "message": "..."} when the site/profile is
        missing. Empty offers list means "mention nothing" — never invent.
    """
    init_db()
    s = get_session()
    try:
        if site_slug:
            site = s.execute(select(Site).where(Site.slug == site_slug)
                             ).scalar_one_or_none()
        else:
            site = s.execute(select(Site).order_by(Site.id.asc())
                             ).scalars().first()
        if site is None:
            return {"status": "error",
                    "message": f"site '{site_slug or 'default'}' not found"}
        profile = load_profile(s, site.id) or {}
        offers = _clean_offers(profile.get("offers"))
        return {"status": "ok", "site": site.slug, "offers": offers,
                "limits": {"max_mentions": MAX_MENTIONS, "max_ctas": MAX_CTAS}}
    finally:
        s.close()


get_offer_catalog_tool = function_tool(
    get_offer_catalog, name_override="get_offer_catalog_tool")
