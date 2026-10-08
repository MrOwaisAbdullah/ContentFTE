"""§7 Local Business Factory tool — provision a ContentFTE site from a
business profile (name, services, locations, tone) as JSON.

Thin wrapper over `lib.factory.provision_site`. Pure DB, no LLM.
"""
from __future__ import annotations

import json
from typing import Any, Dict

from agents import function_tool

from lib.db import get_session, init_db
from lib.factory import provision_site


def provision_factory_site(business_json: str) -> Dict[str, Any]:
    """Create/refresh a site + Brand DNA profile from a business profile.

    Args:
        business_json: JSON object with at least {"name"}; optionally
            {"slug", "site_url", "services", "locations", "tagline",
            "audience", "tone_sliders"…}. (A pre-parsed dict is also accepted
            when this function is called directly.)

    Returns:
        {"status": "ok", "site_id", "slug", "profile_version", "offers",
         "entities"} or {"status": "error", "message": "..."}.
    """
    if isinstance(business_json, str):
        try:
            business = json.loads(business_json)
        except (ValueError, TypeError) as e:
            return {"status": "error", "message": f"business_json is not valid JSON: {e}"}
    else:
        business = business_json
    if not isinstance(business, dict) or not str(business.get("name", "")).strip():
        return {"status": "error", "message": "business name is required"}
    init_db()
    session = get_session()
    try:
        return {"status": "ok", **provision_site(session, business)}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        session.close()


provision_factory_site_tool = function_tool(
    provision_factory_site, name_override="provision_factory_site_tool")
