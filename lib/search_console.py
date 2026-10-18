"""
Google Search Console client for the pipeline. Raw REST calls via `requests`
+ `google.oauth2.service_account.Credentials` (the same GOOGLE_CREDENTIALS
service account already used for Google Sheets, granted Restricted access
separately -- see docs/service_setup.md), rather than pulling in the
google-api-python-client package for what's a handful of simple GET/POST
calls. Approach verified working end-to-end via scripts/test_search_console.py
before this was written.
"""
import hashlib
import json
import logging
import os
import time
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import requests
from google.auth.transport.requests import Request
from google.oauth2.service_account import Credentials

from lib.site_env import SEARCH_CONSOLE_SITE_URL

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
# Default GSC property = this instance's site (site_env); a domain property
# ("sc-domain:...") or per-site override goes in SEARCH_CONSOLE_SITE_URL.
SITE_URL = SEARCH_CONSOLE_SITE_URL

# Per-credential caches: every cached Google connection is keyed by the
# fingerprint of the ACTIVE service-account credentials, so two instances
# that configure different GOOGLE_CREDENTIALS(+_PATH) in one process can
# never reuse each other's token or sites.list answer.
_token_cache: Dict[str, "Credentials"] = {}


def _creds_fingerprint() -> str:
    """Stable identity of the active service account (env JSON, or the
    content of the GOOGLE_CREDENTIALS_PATH file)."""
    raw = os.environ.get("GOOGLE_CREDENTIALS", "").strip()
    if not raw:
        path = os.environ.get("GOOGLE_CREDENTIALS_PATH", "").strip()
        raw = f"path:{path}"
        try:
            with open(path, "rb") as fh:
                raw += ":" + hashlib.sha256(fh.read()).hexdigest()
        except OSError:
            pass
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _get_access_token() -> str:
    """Cached per credential fingerprint, same rationale as
    tools/sheet_tool.py's gspread client caching -- google-auth
    Credentials refresh their own tokens as needed, so it's safe to reuse
    one authorized token across calls in the same process instead of
    re-authenticating every time."""
    creds = _token_cache.get(_creds_fingerprint())
    if creds is None:
        creds_info = json.loads(os.environ["GOOGLE_CREDENTIALS"])
        creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
        _token_cache[_creds_fingerprint()] = creds
    if not creds.valid:
        creds.refresh(Request())
    return creds.token


def query_search_analytics(
    start_date: date,
    end_date: date,
    dimensions: Optional[List[str]] = None,
    row_limit: int = 25,
    dimension_filter_groups: Optional[List[Dict[str, Any]]] = None,
    site_url: str = SITE_URL,
) -> List[Dict[str, Any]]:
    """Queries the Search Analytics API and returns the raw `rows` list
    (each row has `keys` matching `dimensions`, plus `clicks`, `impressions`,
    `ctr`, `position`). Returns an empty list on any failure -- callers
    should treat "no data" and "query failed" the same way (nothing to
    report), logging the distinction rather than raising, since a Search
    Console hiccup shouldn't fail an otherwise-working pipeline stage."""
    body: Dict[str, Any] = {
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "rowLimit": row_limit,
    }
    if dimensions:
        body["dimensions"] = dimensions
    if dimension_filter_groups:
        body["dimensionFilterGroups"] = dimension_filter_groups

    try:
        token = _get_access_token()
        response = requests.post(
            f"https://www.googleapis.com/webmasters/v3/sites/{requests.utils.quote(site_url, safe='')}/searchAnalytics/query",
            headers={"Authorization": f"Bearer {token}"},
            json=body,
            timeout=15,
        )
        response.raise_for_status()
        return response.json().get("rows", [])
    except Exception as e:
        logger.warning(f"query_search_analytics failed: {e}")
        return []


def get_page_performance(page_url: str, days: int = 28) -> Optional[Dict[str, float]]:
    """Convenience wrapper: total clicks/impressions/ctr/avg position for a
    single page over a trailing window. GSC data has a ~2-3 day processing
    lag, so the window ends 3 days ago, not today. Returns None if there's
    no data for that page in the window (not enough traffic to say anything
    meaningful, or the page genuinely isn't indexed/getting impressions)."""
    end = date.today() - timedelta(days=3)
    start = end - timedelta(days=days)
    rows = query_search_analytics(
        start_date=start,
        end_date=end,
        row_limit=1,
        dimension_filter_groups=[{
            "filters": [{"dimension": "page", "operator": "equals", "expression": page_url}]
        }],
    )
    if not rows:
        return None
    row = rows[0]
    return {
        "clicks": row.get("clicks", 0),
        "impressions": row.get("impressions", 0),
        "ctr": row.get("ctr", 0.0),
        "position": row.get("position", 0.0),
    }


def get_page_queries(page_url: str, days: int = 28, row_limit: int = 25) -> List[Dict[str, Any]]:
    """Every query bringing impressions to a single page over a trailing
    window, sorted by impressions descending (Search Console's own default
    row order). Each item: {"query", "clicks", "impressions", "ctr",
    "position"}. This is what makes per-post recommendations concrete --
    "the title isn't compelling enough" is vague, "the query 'X' gets 40
    impressions/month at position 7 with zero clicks" is a specific,
    actionable finding."""
    end = date.today() - timedelta(days=3)
    start = end - timedelta(days=days)
    rows = query_search_analytics(
        start_date=start,
        end_date=end,
        dimensions=["query"],
        row_limit=row_limit,
        dimension_filter_groups=[{
            "filters": [{"dimension": "page", "operator": "equals", "expression": page_url}]
        }],
    )
    return [
        {
            "query": row["keys"][0],
            "clicks": row.get("clicks", 0),
            "impressions": row.get("impressions", 0),
            "ctr": row.get("ctr", 0.0),
            "position": row.get("position", 0.0),
        }
        for row in rows
    ]


def find_striking_distance_queries(
    page_url: str, days: int = 28, min_impressions: int = 5,
    position_low: float = 5.0, position_high: float = 15.0,
) -> List[Dict[str, Any]]:
    """The classic cheap SEO win: queries that already have real impressions
    and sit at position_low-position_high (page 1 bottom / page 2 top) --
    close enough that a small, targeted content tweak (working the exact
    phrase in more prominently, adding a section that answers it directly)
    can plausibly push them onto page 1, unlike a query at position 40 which
    needs a much bigger intervention. Sorted by impressions descending (the
    queries worth targeting first)."""
    queries = get_page_queries(page_url, days=days, row_limit=50)
    candidates = [
        q for q in queries
        if q["impressions"] >= min_impressions and position_low <= q["position"] <= position_high
    ]
    candidates.sort(key=lambda q: q["impressions"], reverse=True)
    return candidates


def get_page_country_device_breakdown(page_url: str, days: int = 28, row_limit: int = 50) -> List[Dict[str, Any]]:
    """Country + device breakdown for a single page over a trailing window.
    Informational context for the reviewer (e.g. "78% of impressions from
    the US, 70% mobile" might justify region-specific examples or a mobile-
    readability check) -- not itself a trigger for flagging a post, just
    context attached to whatever finding did trigger. Each item:
    {"country", "device", "clicks", "impressions"}. Country codes are
    ISO 3166-1 alpha-3 (Search Console's own format, e.g. "usa", "gbr")."""
    end = date.today() - timedelta(days=3)
    start = end - timedelta(days=days)
    rows = query_search_analytics(
        start_date=start,
        end_date=end,
        dimensions=["country", "device"],
        row_limit=row_limit,
        dimension_filter_groups=[{
            "filters": [{"dimension": "page", "operator": "equals", "expression": page_url}]
        }],
    )
    return [
        {
            "country": row["keys"][0],
            "device": row["keys"][1],
            "clicks": row.get("clicks", 0),
            "impressions": row.get("impressions", 0),
        }
        for row in rows
    ]


def get_site_totals(days: int = 7) -> Optional[Dict[str, float]]:
    """Convenience wrapper: site-wide clicks/impressions/avg position over a
    trailing window, no dimensions -- a single summary row. Used for the
    weekly digest's headline numbers."""
    end = date.today() - timedelta(days=3)
    start = end - timedelta(days=days)
    rows = query_search_analytics(start_date=start, end_date=end, row_limit=1)
    if not rows:
        return None
    row = rows[0]
    return {
        "clicks": row.get("clicks", 0),
        "impressions": row.get("impressions", 0),
        "ctr": row.get("ctr", 0.0),
        "position": row.get("position", 0.0),
    }


# ---------------------------------------------------------------------------
# Multi-property support: ONE service account, many properties.
# ---------------------------------------------------------------------------
def resolve_site_property(base_url: str,
                          settings: Optional[Dict[str, Any]] = None) -> str:
    """The GSC property for one site.

    `settings["search_console_site_url"]` wins (an explicit URL-prefix
    property or a domain property "sc-domain:…"); otherwise the property is
    derived from the site's base_url — Search Console URL-prefix properties
    include the trailing slash ("https://example.com/"). Empty string when
    the site has neither, which callers report as "not configured" rather
    than querying a bogus property."""
    override = str((settings or {}).get("search_console_site_url") or "").strip()
    if override:
        return override
    base = (base_url or "").strip().rstrip("/")
    return f"{base}/" if base else ""


# sites.list is one Google call, but the console's Sites screen triggers it
# per page load — cache the answer in-process so a burst of renders (and the
# per-site matching) costs one API call. Keyed by credential fingerprint so
# two instances with different service accounts never share the answer.
# Failures are never cached (the next call retries); the SA token itself is
# cached by _get_access_token.
VISIBLE_CACHE_TTL = 300.0
_visible_cache: Dict[str, Dict[str, Any]] = {}


def list_accessible_properties(max_age: float = VISIBLE_CACHE_TTL,
                               force: bool = False) -> Optional[List[Dict[str, str]]]:
    """sites.list — every property the GOOGLE_CREDENTIALS service account
    can access, with its permission level (owner/full/unrestricted/
    restricted). One service account serves any number of properties; the
    only manual step per property is adding its email under Search Console
    -> Settings -> Users and permissions (Restricted is enough for the
    read-only queries this pipeline makes). Answer cached per credential
    for `max_age` seconds; `force` bypasses. Returns None on auth/API
    failure — callers must report "unknown", never a false "disconnected"."""
    fp = _creds_fingerprint()
    entry = _visible_cache.get(fp, {"at": 0.0, "entries": None})
    now = time.monotonic()
    cached = entry["entries"]
    if (not force and cached is not None
            and now - entry["at"] < max_age):
        return cached
    try:
        token = _get_access_token()
        response = requests.get(
            "https://www.googleapis.com/webmasters/v3/sites",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        response.raise_for_status()
        entries = [
            {"site_url": site.get("siteUrl", ""),
             "permission_level": site.get("permissionLevel", "")}
            for site in response.json().get("siteEntry", [])
        ]
        _visible_cache[fp] = {"at": now, "entries": entries}
        return entries
    except Exception as e:
        logger.warning(f"list_accessible_properties failed: {e}")
        return None


def match_property(property_url: str,
                   visible: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
    """The visible entry covering property_url, or None.

    Exact match first (trailing slash tolerated), then domain-property
    coverage: "sc-domain:example.com" covers every URL-prefix property on
    that host, www or not — the same semantics Search Console itself uses."""
    target = (property_url or "").strip().rstrip("/")

    def _host(url: str) -> str:
        if "://" not in url:
            return ""
        return url.split("//", 1)[-1].split("/", 1)[0].lower().removeprefix("www.")

    host = _host(target)
    for entry in visible:
        url = (entry.get("site_url") or "").strip()
        if url.rstrip("/") == target:
            return entry
        if url.startswith("sc-domain:") and host:
            domain = url.split(":", 1)[1].strip().lower().removeprefix("www.")
            if domain == host:
                return entry
    return None
