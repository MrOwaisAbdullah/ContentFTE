import re
import time
import logging
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit
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

# Statuses that mean "this server will not tell a bot" rather than "the page is gone": a login wall (401),
# a bot block (403 / 999) or a rate limit (429). Treating them as broken made the WordPress publish strip
# perfectly good links to sites that simply dislike HEAD requests from a data centre.
UNVERIFIABLE_STATUSES = frozenset({401, 403, 405, 429, 999})
_NOT_FOUND_SEGMENT = re.compile(r"(^|/)(404|not-?found|page-?not-?found|error)(/|\.|$)", re.I)


def _strip_www(host: str) -> str:
    host = (host or "").lower()
    return host[4:] if host.startswith("www.") else host


def _is_soft_404(requested: str, final: str) -> bool:
    """A 'successful' response that is really a missing page: a hallucinated deep link that the site
    redirects to its homepage (or to a /404 page). Compares the path that was asked for with the one that
    was finally served."""
    if not final or final == requested:
        return False
    a, b = urlsplit(requested), urlsplit(final)
    asked = (a.path or "/").rstrip("/") or "/"
    served = (b.path or "/").rstrip("/") or "/"
    if asked == served:
        return False
    if _NOT_FOUND_SEGMENT.search(served) and not _NOT_FOUND_SEGMENT.search(asked):
        return True
    return asked != "/" and served == "/" and _strip_www(a.hostname or "") == _strip_www(b.hostname or "")


def _head_ok(url: str, timeout: float = 8.0) -> Tuple[bool, Optional[int]]:
    # Link targets come from LLM drafts: an internal/metadata/loopback URL (or a public one that
    # redirects to one) must be reported as an invalid link, never requested (plan SEC-05).
    hdrs = {"User-Agent": "Mozilla/5.0 ContentFTE-link-validator"}
    try:
        r = safe_head(url, timeout=timeout, headers=hdrs)
        if r.status_code in (405, 501):
            r = safe_get(url, timeout=timeout, headers=hdrs, max_bytes=256 * 1024)
        if 200 <= r.status_code < 400 and _is_soft_404(url, str(getattr(r, "url", "") or "")):
            logger.info(f"Soft 404: {url} was served as {r.url}")
            return False, r.status_code
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
            unverifiable = (not ok) and status in UNVERIFIABLE_STATUSES
            # unverifiable != broken: keep the link (a warning, not a strip)
            entry = {**l, "valid": ok or unverifiable, "status": status, "kind": "external",
                     "unverifiable": unverifiable}
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
