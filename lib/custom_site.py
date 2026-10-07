"""§5.12 custom-site SDK delivery — hand an article to a self-hosted site.

Frontend-first: the engine owns the *content*, the site (Astro/Next/React)
owns the layout. Delivery has two shapes:
- **pull** — the site fetches `GET /sdk/v1/articles/{id}/content` (already
  exposed by `sdk/service.get_article(include_content=True)`).
- **push** — the engine POSTs a rendered payload to a configured webhook
  (`SITE_PUBLISH_WEBHOOK`): the site's build hook / API route.

`build_delivery_payload` renders HTML (lib.wp_render), the `.md` alternate and
Article/FAQ JSON-LD (lib.geo) once, so every consumer gets identical content.
Pure composition + a single best-effort HTTP POST; no LLM.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import requests

from lib import wp_render
from lib.geo import article_schema, faq_schema as build_faq_schema, markdown_alternate


def build_delivery_payload(
    *,
    title: str,
    markdown: str,
    meta_description: str = "",
    slug: str = "",
    url: str = "",
    faqs: Optional[List[Dict[str, Any]]] = None,
    date_published: Optional[str] = None,
    date_modified: Optional[str] = None,
) -> Dict[str, Any]:
    """Rendered, site-agnostic payload for a custom site (Astro/Next/React)."""
    return {
        "title": title,
        "slug": slug or title,
        "url": url,
        "excerpt": meta_description,
        "html": wp_render.markdown_to_wp_html(markdown, blocks=False),
        "markdown": markdown,
        "markdown_alternate": markdown_alternate(title, markdown, {"description": meta_description}),
        "schema": {
            "article": article_schema(title, url or slug, date_published, date_modified),
            "faq": build_faq_schema(faqs) if faqs else None,
        },
    }


def deliver(
    payload: Dict[str, Any],
    webhook_url: str = "",
    timeout: float = 30.0,
) -> Dict[str, Any]:
    """POST the payload to the site's publish webhook. Best-effort; never raises.

    Returns {"status": "ok", "status_code"} or {"status": "error", "message"}.
    No webhook configured is an error the caller surfaces (nothing was pushed),
    not a silent success.
    """
    url = (webhook_url or os.environ.get("SITE_PUBLISH_WEBHOOK") or "").strip()
    if not url:
        return {"status": "error",
                "message": "no SITE_PUBLISH_WEBHOOK configured — use the SDK pull route instead"}
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        return {"status": "ok", "status_code": resp.status_code}
    except Exception as e:
        return {"status": "error", "message": str(e)}
