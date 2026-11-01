"""§5.6 URL submission on publish — IndexNow + Bing WMT (concrete mechanism).

The spec wants "IndexNow ping + Bing Webmaster Tools API submission — a
concrete mechanism, not just the ping". Two concrete paths, both best-effort
and fail-open (a search-engine notification must never fail a publish):

- **IndexNow** — one POST to the shared endpoint fans out to every
  participating engine (Bing, Yandex, Seznam, ...). Spec shape:
  ``{host, key, keyLocation?, urlList}``, ``Content-Type:
  application/json; charset=utf-8``. 200 = processed; 202 = received, key
  verification pending (first request). The key must be hosted as a UTF-8
  ``{key}.txt`` file at the site root (or a ``keyLocation`` we pass) —
  that part is the operator's one-time setup.
  Ref: https://www.indexnow.org/documentation (2026-10-08).

- **Bing Webmaster Tools URL Submission API** — the direct Bing-only
  endpoint for publish pipelines that don't rely on IndexNow fan-out:
  ``POST https://ssl.bing.com/webmaster/api.svc/json/SubmitUrlBatch?apikey=…``
  with ``{"siteUrl": …, "urlList": [...]}`` (≤500 URLs/batch; 200 OK).
  Ref: https://www.bing.com/webmasters/help/URL-Submission-62f2860b.

Env: ``INDEXNOW_KEY`` (hex, 8-128 chars), ``BING_WMT_API_KEY`` (BWT →
Settings → API access), ``INDEXING_ENABLED=0`` to suppress both.
Reading either key enables its path; no keys set → ``skipped``.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

import requests
from lib.redact import redact_text

INDEXNOW_ENDPOINTS = ("https://api.indexnow.org/indexnow",
                      "https://www.bing.com/indexnow")
BING_WMT_SUBMIT_URL = "https://ssl.bing.com/webmaster/api.svc/json/SubmitUrlBatch"
_TIMEOUT = 10
_ACCEPT = (200, 201, 202)


def _enabled() -> bool:
    return (os.environ.get("INDEXING_ENABLED") or "1").strip().lower() \
        not in {"0", "off", "false", "no"}


def _clean(urls: Iterable[str]) -> List[str]:
    out, seen = [], set()
    for u in urls or []:
        u = str(u or "").strip()
        if u and u.startswith(("http://", "https://")) and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def indexnow_key_location(base_url: str, key: str) -> str:
    """Root-hosted key file URL (the default location; documented shape)."""
    return f"{(base_url or '').rstrip('/')}/{key}.txt"


def submit_indexnow(urls: Iterable[str], *, base_url: str, key: str,
                    endpoints: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """POST the IndexNow payload to each endpoint. Never raises."""
    url_list = _clean(urls)
    if not url_list:
        return {"ok": False, "error": "no valid http(s) urls"}
    host = urlparse(base_url or url_list[0]).netloc
    payload: Dict[str, Any] = {
        "host": host,
        "key": key,
        "keyLocation": indexnow_key_location(base_url or f"https://{host}", key),
        "urlList": url_list,
    }
    results = []
    for endpoint in endpoints or INDEXNOW_ENDPOINTS:
        try:
            resp = requests.post(
                endpoint, json=payload, timeout=_TIMEOUT,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
            results.append({
                "endpoint": endpoint,
                "ok": resp.status_code in _ACCEPT,
                "status": resp.status_code,
                **({} if resp.status_code in _ACCEPT
                   else {"body": (resp.text or "")[:300]}),
            })
        except Exception as exc:  # network — fail-open, report
            results.append({"endpoint": endpoint, "ok": False,
                            "error": str(exc)[:300]})
    return {"ok": any(r.get("ok") for r in results), "host": host,
            "urls": len(url_list), "results": results}


def submit_bing_wmt(urls: Iterable[str], *, site_url: str,
                    api_key: str) -> Dict[str, Any]:
    """Bing Webmaster Tools SubmitUrlBatch. Never raises."""
    url_list = _clean(urls)
    if not url_list:
        return {"ok": False, "error": "no valid http(s) urls"}
    try:
        resp = requests.post(
            f"{BING_WMT_SUBMIT_URL}?apikey={api_key}",
            json={"siteUrl": site_url, "urlList": url_list[:500]},
            timeout=_TIMEOUT,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        out: Dict[str, Any] = {"ok": resp.status_code in _ACCEPT,
                               "status": resp.status_code,
                               "urls": len(url_list)}
        if resp.status_code not in _ACCEPT:
            out["body"] = redact_text((resp.text or "")[:300])
        return out
    except Exception as exc:
        # requests' exception text quotes the full URL, including ?apikey=... (plan SEC-11).
        return {"ok": False, "error": redact_text(str(exc))[:300]}


def submit_published(url: str, *, site_url: str = "", indexnow_key: str = "",
                     bing_key: str = "", env_fallback: Optional[bool] = None) -> Dict[str, Any]:
    """Publish-path orchestrator: ping every enabled engine for ONE url.

    Keys are per site (`Site.settings["indexing"]`), passed in by the caller: IndexNow verifies the key
    by fetching `https://<host>/<key>.txt`, so a key that belongs to one host is rejected for every other
    tenant's host (ADP-15). The environment keys are the single-site fallback; in shared (multi-tenant)
    mode they are NOT used unless `env_fallback=True`, because they would only ever fail there.

    Best-effort by contract — called after the status flip in
    ``service.publish_article`` / ``refresh_article``; returns a report dict
    that rides the response and never raises.
    """
    if not _enabled():
        return {"skipped": "INDEXING_ENABLED=0"}
    url = str(url or "").strip()
    if not url.startswith(("http://", "https://")):
        return {"skipped": "no live url to submit"}
    site = (site_url or "").rstrip("/") or \
        f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    out: Dict[str, Any] = {"url": url, "site": site}
    if env_fallback is None:
        from lib.site_env import is_shared_mode
        env_fallback = not is_shared_mode()
    def pick(own: str, env_name: str) -> str:
        own = (own or "").strip()
        return own or ((os.environ.get(env_name) or "").strip() if env_fallback else "")

    key = pick(indexnow_key, "INDEXNOW_KEY")
    if key:
        out["indexnow"] = submit_indexnow([url], base_url=site, key=key)
    bing = pick(bing_key, "BING_WMT_API_KEY")
    if bing:
        out["bing_wmt"] = submit_bing_wmt([url], site_url=site, api_key=bing)
    if "indexnow" not in out and "bing_wmt" not in out:
        out["skipped"] = ("no IndexNow / Bing key configured for this site "
                          "(Site.settings.indexing.indexnow_key / bing_wmt_key)"
                          if not env_fallback else "INDEXNOW_KEY / BING_WMT_API_KEY not set")
    return out
