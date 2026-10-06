"""ContentFTE Python SDK client (§5.12). Copy-paste quickstart in docstring."""
from __future__ import annotations

import time

import requests

RETRY_STATUSES = {429, 500, 502, 503, 504}


class ContentFTEClient:
    """Quickstart:
    client = ContentFTEClient("https://engine.example.com", "site-key")
    art = client.submit_article("mysite", keyword="best crm for agencies")
    client.approve_article(art["id"], True)
    content = client.get_content(art["id"])

    Transient failures (connection errors, 429/5xx) are retried with
    exponential backoff: up to 3 attempts at 0.5s / 1s / 2s.
    Pair POSTs with an idempotency_key — retries then never duplicate
    an article server-side.
    """

    def __init__(self, base_url: str, site_key: str, timeout: float = 20.0,
                 max_retries: int = 3, backoff: float = 0.5):
        self.base = base_url.rstrip("/")
        self.headers = {"X-Site-Key": site_key}
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff

    def _request(self, method: str, path: str, json: dict | None = None,
                 headers: dict | None = None) -> dict:
        url = f"{self.base}{path}"
        hdrs = {**self.headers, **(headers or {})}
        delay = self.backoff
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = requests.request(method, url, json=json, headers=hdrs,
                                        timeout=self.timeout)
                if resp.status_code in RETRY_STATUSES and attempt < self.max_retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException as exc:
                last_exc = exc
                if attempt >= self.max_retries:
                    break
                time.sleep(delay)
                delay *= 2
        raise last_exc  # type: ignore[misc]

    def submit_article(self, site_slug: str, keyword: str = "", brief: dict | None = None,
                       idempotency_key: str = "") -> dict:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
        return self._request("POST", "/sdk/v1/articles",
                             json={"site_slug": site_slug, "keyword": keyword,
                                   "brief": brief or {}},
                             headers=headers)

    def get_article(self, article_id: int) -> dict:
        return self._request("GET", f"/sdk/v1/articles/{article_id}")

    def approve_article(self, article_id: int, approved: bool = True, note: str = "") -> dict:
        return self._request("POST", f"/sdk/v1/articles/{article_id}/approve",
                             json={"approved": approved, "note": note})

    def publish_article(self, article_id: int, mode: str = "draft") -> dict:
        return self._request("POST", f"/sdk/v1/articles/{article_id}/publish",
                             json={"mode": mode})

    def get_content(self, article_id: int) -> dict:
        return self._request("GET", f"/sdk/v1/articles/{article_id}/content")

    def list_sites(self) -> dict:
        return self._request("GET", "/sdk/v1/sites")

    def upsert_site(self, slug: str, name: str = "", site_type: str = "custom",
                    base_url: str = "") -> dict:
        return self._request("POST", "/sdk/v1/sites",
                             json={"slug": slug, "name": name,
                                   "site_type": site_type, "base_url": base_url})
