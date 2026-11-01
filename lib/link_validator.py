import re
import time
import logging
from typing import Any, Dict, List, Optional, Tuple
import requests
from lib.safe_fetch import UnsafeURL, safe_get, safe_head

from lib.site_env import SITE_HOST, SITE_PREFIX

logger = logging.getLogger(__name__)

REL_PREFIX = "/blog/"
MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\s\)]+|/blog/[^\s\)]+)\)")

def extract_markdown_links(markdown: str) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for m in MD_LINK_RE.finditer(markdown or ""):
        out.append({"text": m.group(1), "url": m.group(2), "raw": m.group(0)})
    return out

def _is_internal_url(url: str) -> bool:
    return url.startswith(SITE_PREFIX) or url.startswith(REL_PREFIX) or SITE_HOST in url and "/blog/" in url

def _normalize_internal_slug(url: str) -> str:
    u = url.strip()
    if u.startswith(SITE_PREFIX):
        return u[len(SITE_PREFIX):].split("?")[0].split("#")[0].strip("/")
    if u.startswith(REL_PREFIX):
        return u[len(REL_PREFIX):].split("?")[0].split("#")[0].strip("/")
    if SITE_HOST in u:
        try:
            part = u.split("/blog/", 1)[1]
            return part.split("?")[0].split("#")[0].strip("/")
        except IndexError:
            return u
    return u

def _has_sanity_config() -> bool:
    import os
    return bool(os.environ.get("SANITY_PROJECT_ID") and os.environ.get("SANITY_DATASET"))

def _sanity_slug_exists(slug: str) -> bool:
    if not _has_sanity_config():
        return True
    try:
        from lib.sanity_adapter import SanityAdapter
        adapter = SanityAdapter()
        q = '*[_type == "post" && slug.current == $slug][0]{slug}'
        endpoint = adapter._build_query_endpoint(q, {"slug": slug}, perspective="published")
        resp = adapter._make_request("GET", endpoint)
        resp.raise_for_status()
        result = resp.json().get("result")
        return bool(result)
    except Exception as e:
        logger.warning(f"Sanity slug check failed for '{slug}': {e}")
        return True

def _head_ok(url: str, timeout: float = 8.0) -> Tuple[bool, Optional[int]]:
    # Link targets come from LLM drafts: an internal/metadata/loopback URL (or a public one that
    # redirects to one) must be reported as an invalid link, never requested (plan SEC-05).
    hdrs = {"User-Agent": "Mozilla/5.0 ContentFTE-link-validator"}
    try:
        r = safe_head(url, timeout=timeout, headers=hdrs)
        if r.status_code in (405, 501):
            r = safe_get(url, timeout=timeout, headers=hdrs, max_bytes=256 * 1024)
        return 200 <= r.status_code < 400, r.status_code
    except UnsafeURL as e:
        logger.warning(f"Refusing to fetch link {url}: {e}")
        return False, None
    except Exception as e:
        logger.info(f"HEAD failed for {url}: {e}")
        return False, None

def validate_links(markdown: str, known_internal_slugs: Optional[List[str]] = None, check_external_head: bool = True, external_head_timeout: float = 8.0) -> Dict[str, Any]:
    links = extract_markdown_links(markdown)
    internal: List[Dict[str, Any]] = []
    external: List[Dict[str, Any]] = []
    known_set = set(s.strip("/").lower() for s in (known_internal_slugs or [])) if known_internal_slugs is not None else None
    for l in links:
        url = l["url"]
        if _is_internal_url(url):
            slug = _normalize_internal_slug(url)
            if known_set is not None:
                ok = slug.lower() in known_set
            else:
                ok = _sanity_slug_exists(slug)
            entry = {**l, "slug": slug, "valid": ok, "kind": "internal"}
            internal.append(entry)
        else:
            ok = True
            status: Optional[int] = None
            if check_external_head:
                ok, status = _head_ok(url, timeout=external_head_timeout)
            entry = {**l, "valid": ok, "status": status, "kind": "external"}
            external.append(entry)
    invalid_internal = [x for x in internal if not x["valid"]]
    invalid_external = [x for x in external if not x["valid"]]
    return {
        "links": links,
        "internal": internal,
        "external": external,
        "invalid_internal": invalid_internal,
        "invalid_external": invalid_external,
        "has_invalid": bool(invalid_internal or invalid_external),
    }

def strip_invalid_links(markdown: str, validation: Dict[str, Any]) -> str:
    out = markdown or ""
    for bad in validation.get("invalid_internal", []) + validation.get("invalid_external", []):
        raw = bad.get("raw")
        text = bad.get("text", "")
        if raw and raw in out:
            out = out.replace(raw, text)
    return out
