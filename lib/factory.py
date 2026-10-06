"""§7 Local Business Factory — business profile → ContentFTE site.

Maps a converted tenant's business profile (name, services, locations, tone)
into a ContentFTE Site plus a Brand DNA profile:

- the profile is shaped for `lib.brand_dna.save_profile` (voice + reading level
  + entity list), and
- it carries an `offers` list in the exact shape `tools/offer_tool.py` reads
  ({name, description, url, cta}) so the brief/draft agents can place them.

Pure: no LLM, no network. The later "publish via Astro/SDK" step (Phase 1.5)
consumes the site this creates.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from lib.brand_dna import save_profile
from lib.geo import slugify_taxonomy
from lib.store import get_or_create_site

# AI-writing tells / generic-agency words a local business never says.
DEFAULT_BANNED = [
    "revolutionize", "revolutionise", "paradigm shift", "game-changer",
    "unleash", "seamless", "cutting-edge", "world-class", "synergy",
]


def _service_list(services: List[Any]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for s in services or []:
        if isinstance(s, str) and s.strip():
            out.append({"name": s.strip(), "description": "", "cta": ""})
        elif isinstance(s, dict) and s.get("name"):
            out.append({
                "name": str(s.get("name", "")).strip(),
                "description": str(s.get("description", "") or "").strip(),
                "cta": str(s.get("cta", "") or "").strip(),
                "url": str(s.get("url", "") or "").strip(),
            })
    return out


def build_offer_catalog(
    services: List[Any], site_url: str = "", default_cta: str = "Get a quote"
) -> List[Dict[str, str]]:
    """Services → offer catalog (offer_tool-compatible shape)."""
    base = (site_url or "").rstrip("/")
    offers: List[Dict[str, str]] = []
    for s in _service_list(services):
        url = s.get("url") or (
            f"{base}/services/{slugify_taxonomy(s['name'])}/" if base else ""
        )
        offers.append({
            "name": s["name"],
            "description": s["description"],
            "url": url,
            "cta": s["cta"] or default_cta,
        })
    return offers


def build_brand_profile(business: Dict[str, Any]) -> Dict[str, Any]:
    """Business profile → Brand DNA dict (save_profile-compatible + offers)."""
    business = business or {}
    name = str(business.get("name", "")).strip()
    services = _service_list(business.get("services"))
    locations = [str(loc).strip() for loc in (business.get("locations") or []) if str(loc).strip()]

    entities = [name] if name else []
    entities += [s["name"] for s in services]
    entities += locations
    # de-dup, preserve order
    seen = set()
    entities = [e for e in entities if not (e.lower() in seen or seen.add(e.lower()))]

    return {
        "brand_name": name,
        "tagline": str(business.get("tagline", "") or "").strip(),
        "audience": str(business.get("audience", "") or "").strip(),
        "site_url": str(business.get("site_url", "") or "").strip(),
        "tone_sliders": {
            "formal_casual": float(business.get("formal_casual", 0.4)),
            "terse_expansive": float(business.get("terse_expansive", 0.4)),
        },
        "reading_level": str(business.get("reading_level") or "grade-8"),
        "signature_phrases": list(business.get("signature_phrases") or []),
        "banned_phrases": list(business.get("banned_phrases") or DEFAULT_BANNED),
        "pov": str(business.get("pov") or "second"),
        "style_preset": str(business.get("style_preset") or "photoreal"),
        "entities": entities,
        "offers": build_offer_catalog(services, business.get("site_url", "")),
    }


def site_slug(business: Dict[str, Any]) -> str:
    business = business or {}
    return str(business.get("slug") or slugify_taxonomy(str(business.get("name", "")))).strip()


def provision_site(session: Session, business: Dict[str, Any]) -> Dict[str, Any]:
    """Create/update the ContentFTE Site and save its Brand DNA profile."""
    slug = site_slug(business)
    site = get_or_create_site(session, slug)
    site.name = str(business.get("name") or site.name).strip() or site.name
    site.site_type = str(business.get("site_type") or site.site_type or "wordpress")
    if business.get("site_url"):
        site.base_url = str(business["site_url"]).rstrip("/")
    session.commit()
    session.refresh(site)

    profile = build_brand_profile(business)
    row = save_profile(session, site.id, profile)
    return {"site_id": site.id, "slug": site.slug, "profile_version": row.version,
            "offers": len(profile["offers"]), "entities": len(profile["entities"])}
