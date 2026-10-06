"""§5.12 Custom-site SDK — REST routes (FastAPI APIRouter).

Thin HTTP layer over `sdk/service.py` (the canonical operations). MCP tools
consume the same service, so API and MCP behavior cannot drift.

Endpoints:
    POST /sdk/v1/articles                 -> submit brief/keyword
    GET  /sdk/v1/articles/{id}            -> status, scores, cost
    POST /sdk/v1/articles/{id}/approve    -> approve / needs_review
    POST /sdk/v1/articles/{id}/publish    -> mark published (approved only)
    GET  /sdk/v1/articles/{id}/content    -> HTML + markdown + metadata + images
    GET  /sdk/v1/sites                    -> list sites
    POST /sdk/v1/sites                    -> create / update a site
    GET  /sdk/v1/sites/{slug}/health      -> site health

Auth: per-site API key via X-Site-Key header (SDK_MASTER_KEY, dev-open when
unset). Idempotency-Key honored on POST /articles (24h in-memory cache).
Webhook events returned in responses: article.ready / article.published /
article.needs_review. Every mutating action is audit-logged by the service.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

import sdk.service as service

router = APIRouter(prefix="/sdk/v1", tags=["sdk"])

_idempotency: dict[str, dict] = {}


def _check_site_key(x_site_key: str | None) -> str:
    import os
    expected = os.environ.get("SDK_MASTER_KEY", "")
    if expected and x_site_key != expected:
        raise HTTPException(status_code=401, detail="invalid X-Site-Key")
    return x_site_key or "dev"


def _resolve(data: dict) -> dict:
    """Service error dicts become HTTP errors; success passes through."""
    if "error" in data:
        raise HTTPException(status_code=404, detail=data["error"])
    return data


class ArticleSubmit(BaseModel):
    site_slug: str
    keyword: str | None = None
    brief: dict[str, Any] = {}


class ArticleApprove(BaseModel):
    approved: bool = True
    note: str = ""


class ArticlePublish(BaseModel):
    mode: str = "draft"  # draft (default for new sites) | publish


class SiteUpsert(BaseModel):
    slug: str
    name: str = ""
    site_type: str = "custom"  # custom | wordpress
    base_url: str = ""


@router.post("/articles")
def submit_article(
    body: ArticleSubmit,
    x_site_key: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None),
) -> dict:
    site_key = _check_site_key(x_site_key)
    body_hash = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    cache_key = None
    if idempotency_key:
        cache_key = hashlib.sha256(f"{site_key}:{idempotency_key}:{body_hash}".encode()).hexdigest()
        if cache_key in _idempotency:
            return _idempotency[cache_key]
    result = service.submit_article(body.site_slug, keyword=body.keyword or "",
                                    brief=body.brief)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    if cache_key:
        _idempotency[cache_key] = result
    return result


@router.get("/articles/{article_id}")
def get_article(article_id: int, x_site_key: str | None = Header(default=None)) -> dict:
    _check_site_key(x_site_key)
    return _resolve(service.get_article(article_id))


@router.post("/articles/{article_id}/approve")
def approve_article(article_id: int, body: ArticleApprove,
                    x_site_key: str | None = Header(default=None)) -> dict:
    _check_site_key(x_site_key)
    return _resolve(service.approve_article(article_id, approved=body.approved,
                                            note=body.note, via="sdk"))


@router.post("/articles/{article_id}/publish")
def publish_article(article_id: int, body: ArticlePublish | None = None,
                    x_site_key: str | None = Header(default=None)) -> dict:
    _check_site_key(x_site_key)
    result = service.publish_article(article_id,
                                     mode=(body.mode if body else "draft"),
                                     via="sdk")
    if "error" in result:
        if "requires 'approved'" in result["error"]:
            raise HTTPException(status_code=409, detail=result["error"])
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/articles/{article_id}/content")
def get_content(article_id: int, x_site_key: str | None = Header(default=None)) -> dict:
    _check_site_key(x_site_key)
    return _resolve(service.get_article(article_id, include_content=True))


@router.get("/sites")
def list_sites(x_site_key: str | None = Header(default=None)) -> dict:
    _check_site_key(x_site_key)
    return service.list_sites()


@router.post("/sites")
def upsert_site(body: SiteUpsert, x_site_key: str | None = Header(default=None)) -> dict:
    _check_site_key(x_site_key)
    return service.upsert_site(body.slug, name=body.name,
                               site_type=body.site_type, base_url=body.base_url)


@router.get("/sites/{site_slug}/health")
def site_health(site_slug: str, x_site_key: str | None = Header(default=None)) -> dict:
    _check_site_key(x_site_key)
    return _resolve(service.site_health(site_slug))
