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

import hashlib
import hmac
import json
import os
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

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
    focus_keyword: str = "",
    tldr: str = "",
    schema_extra: Optional[Dict[str, Any]] = None,
    meta_title: str = "",
    canonical: str = "",
    featured_image: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Rendered, site-agnostic payload for a custom site (Astro/Next/React).

    v2 (ADP-07) adds what a page needs to emit correct head tags without re-deriving it: a distinct
    `seo.meta_title` (falls back to the title), `seo.canonical` (the article URL), the `image` (featured
    image url/alt/size) and a ready-made `og` block. The SDK's `buildMetadata(payload)` maps these to a
    Next.js `generateMetadata()` result."""
    from lib.geo import extract_tldr

    page_url = canonical or url
    img = featured_image if isinstance(featured_image, dict) and featured_image.get("url") else None
    description = meta_description

    payload = {
        "title": title,
        "slug": slug or title,
        "url": url,
        "excerpt": meta_description,
        "html": wp_render.markdown_to_wp_html(markdown, blocks=False),
        "markdown": markdown,
        "markdown_alternate": markdown_alternate(title, markdown, {"description": meta_description}),
        # FAQ accordion HTML for sites that don't render markdown themselves
        # (React can use <ContentFTEFaq> instead). Same <details> markup as the
        # WordPress + Elementor output — FAQs are always an accordion.
        "faq_html": wp_render.render_faq_block(faqs, blocks=False) if faqs else "",
        "schema": {
            "article": article_schema(title, url or slug, date_published, date_modified,
                                      **(schema_extra or {})),
            "faq": build_faq_schema(faqs) if faqs else None,
        },
        # SEO + AEO fields as first-class values. Before this, a custom site
        # got the meta description only as `excerpt` and had to parse the
        # TL;DR blockquote out of the markdown itself to render meta tags or
        # hand answer engines a quotable sentence. Mirrors what the Sanity
        # schema stores (sdk/sanity/postType.ts) and what WordPress already
        # received as Yoast/Rank Math fields.
        "seo": {
            "title": title,
            "meta_title": (meta_title or "").strip() or title,
            "description": meta_description,
            "canonical": page_url,
            "focus_keyword": focus_keyword,
            "tldr": tldr or extract_tldr(markdown),
        },
        "image": img,
        "og": {
            "type": "article",
            "title": (meta_title or "").strip() or title,
            "description": description,
            "url": page_url,
            "image": (img or {}).get("url", ""),
            "image_alt": (img or {}).get("alt", ""),
            "published_time": date_published or "",
            "modified_time": date_modified or "",
        },
        "payload_version": 2,
    }
    return payload


SIGNATURE_HEADER = "X-CFTE-Signature"
DELIVERY_HEADER = "X-CFTE-Delivery"
TIMESTAMP_HEADER = "X-CFTE-Timestamp"
DEFAULT_TOLERANCE_SECONDS = 300


def canonical_body(payload: Dict[str, Any]) -> bytes:
    """The exact bytes that are signed AND sent (sorted keys, no whitespace), so a receiver can verify the
    signature over the raw request body without re-serialising anything."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      default=str).encode("utf-8")


def sign(secret: str, body: bytes, timestamp: Optional[int] = None) -> str:
    """`t=<unix>,v1=<hex HMAC-SHA256(secret, "<t>." + body)>` - the timestamp is inside the MAC, so a
    captured delivery cannot be replayed later or have its timestamp swapped."""
    ts = int(time.time() if timestamp is None else timestamp)
    mac = hmac.new(secret.encode("utf-8"), f"{ts}.".encode("utf-8") + body, hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


def verify_signature(secret: str, body: bytes, header: str,
                     tolerance: int = DEFAULT_TOLERANCE_SECONDS, now: Optional[float] = None) -> bool:
    """Reference verifier (the same algorithm a site implements): constant-time MAC compare, and the
    timestamp must be within `tolerance` seconds. Returns False on any malformed header."""
    try:
        parts = dict(p.split("=", 1) for p in (header or "").split(","))
        ts = int(parts["t"])
        got = parts["v1"]
    except (KeyError, ValueError):
        return False
    if abs((time.time() if now is None else now) - ts) > tolerance:
        return False
    want = sign(secret, body, ts).split("v1=", 1)[1]
    return hmac.compare_digest(want, got)


def _retryable(status: int) -> bool:
    return status == 429 or status >= 500


def deliver(
    payload: Dict[str, Any],
    webhook_url: str = "",
    timeout: float = 30.0,
    *,
    secret: str = "",
    max_attempts: int = 3,
    backoff: float = 1.5,
    sleep: Callable[[float], None] = time.sleep,
    delivery_id: str = "",
) -> Dict[str, Any]:
    """POST the payload to the site's publish webhook. Best-effort; never raises.

    Signed when a secret is given (`secret=` or SITE_PUBLISH_SECRET): `X-CFTE-Signature: t=..,v1=..`
    over the exact body, plus `X-CFTE-Delivery` - one id for every attempt of this delivery, so the site
    can de-duplicate a retry that raced a slow success (SEC-13 / ADP-04). Network errors, 429 and 5xx are
    retried with exponential backoff; any other 4xx is final (retrying cannot change the answer).
    Redirects are not followed: the signed body is only ever sent to the URL that was configured.

    Returns {"status": "ok", "status_code", "delivery_id", "attempts"} or
    {"status": "error", "message", "delivery_id", "attempts"}. No webhook configured is an error the caller
    surfaces (nothing was pushed), not a silent success.
    """
    url = (webhook_url or os.environ.get("SITE_PUBLISH_WEBHOOK") or "").strip()
    if not url:
        return {"status": "error",
                "message": "no SITE_PUBLISH_WEBHOOK configured — use the SDK pull route instead"}
    secret = (secret or os.environ.get("SITE_PUBLISH_SECRET") or "").strip()
    body = canonical_body(payload)
    delivery_id = delivery_id or str(uuid.uuid4())      # a queued retry passes its original id back in
    last = "no attempt made"
    for attempt in range(1, max(1, max_attempts) + 1):
        headers = {"Content-Type": "application/json; charset=utf-8", DELIVERY_HEADER: delivery_id,
                   "User-Agent": "ContentFTE-delivery/1"}
        if secret:
            stamp = int(time.time())
            headers[TIMESTAMP_HEADER] = str(stamp)
            headers[SIGNATURE_HEADER] = sign(secret, body, stamp)     # re-signed per attempt: fresh timestamp
        try:
            resp = requests.post(url, data=body, headers=headers, timeout=timeout, allow_redirects=False)
            code = int(getattr(resp, "status_code", 0) or 0)
            if 200 <= code < 300:
                return {"status": "ok", "status_code": code, "delivery_id": delivery_id,
                        "attempts": attempt, "signed": bool(secret)}
            last = f"HTTP {code}"
            if not _retryable(code):
                break
        except Exception as e:  # noqa: BLE001 - network errors are retryable
            last = str(e)
        if attempt < max_attempts:
            sleep(backoff ** attempt)
    return {"status": "error", "message": last, "delivery_id": delivery_id, "attempts": attempt}
