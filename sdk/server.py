"""§5.12 Custom-site SDK — REST routes (FastAPI APIRouter).

Thin HTTP layer over `sdk/service.py` (the canonical operations). MCP tools
consume the same service, so API and MCP behavior cannot drift.

Endpoints:
    POST /sdk/v1/articles                 -> submit brief/keyword
    GET  /sdk/v1/articles/{id}            -> status, scores, cost
    POST /sdk/v1/articles/{id}/generate   -> run real generation (briefed -> drafted)
    POST /sdk/v1/articles/{id}/approve    -> approve / needs_review
    POST /sdk/v1/articles/{id}/publish    -> mark published (approved only);
                                             site_type="wordpress" sites are
                                             pushed to WP in the same call
                                             ({"wp": {...}} in the response)
    GET  /sdk/v1/articles/{id}/content    -> unified delivery payload
                                             (html + markdown + meta + JSON-LD)
    GET  /sdk/v1/sites                    -> list sites
    POST /sdk/v1/sites                    -> create / update a site
    GET  /sdk/v1/sites/{slug}/health      -> site health
    GET  /sdk/v1/elementor/available      -> Elementor REST meta probe (status body)
    GET  /sdk/v1/elementor/posts/{id}     -> current Elementor document (elements)
    POST /sdk/v1/elementor/posts/{id}     -> replace the document (elements, page_settings)
    POST /sdk/v1/elementor/articles/{id}/build -> compose article as Elementor doc

Auth: per-site API key via X-Site-Key header (SDK_MASTER_KEY, dev-open when
unset). Idempotency-Key honored on POST /articles (24h in-memory cache).
Webhook events returned in responses: article.ready / article.drafted /
article.published / article.needs_review. Every mutating action is
audit-logged by the service.
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


class ArticleGenerate(BaseModel):
    regenerate: bool = False  # true = rewrite an article that already has content


class ArticlePublish(BaseModel):
    mode: str = "draft"  # draft (default for new sites) | publish


class SiteUpsert(BaseModel):
    slug: str
    name: str = ""
    site_type: str = "custom"  # custom | wordpress
    base_url: str = ""


class ElementorSave(BaseModel):
    elements: list[dict[str, Any]]
    page_settings: dict[str, Any] | None = None
    post_type: str = "posts"  # posts | pages (whitelisted in the service)


class ElementorBuild(BaseModel):
    post_id: int | None = None  # omit → create (or reuse meta.wp_post_id)
    mode: str = "draft"  # draft (default) | auto


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


@router.post("/articles/{article_id}/generate")
async def generate_article(article_id: int, body: ArticleGenerate | None = None,
                           x_site_key: str | None = Header(default=None)) -> dict:
    """Run real generation for a submitted article (briefed -> drafted, §5.5).
    Long-running (LLM, typically 30-120s) — idempotent: articles that
    already have content return as-is unless regenerate=true."""
    _check_site_key(x_site_key)
    result = await service.generate_content(
        article_id, regenerate=bool(body and body.regenerate))
    if "error" in result:
        if "not found" in result["error"]:
            raise HTTPException(status_code=404, detail=result["error"])
        if result["error"].startswith(("generation failed", "agent returned",
                                       "generated content")):
            raise HTTPException(status_code=502, detail=result["error"])
        raise HTTPException(status_code=400, detail=result["error"])
    return result


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


# --- Elementor (§5.11/§5.13 — native REST target) ---


@router.get("/elementor/available")
def elementor_available(x_site_key: str | None = Header(default=None)) -> dict:
    """Preflight: 200 always — the body carries available/flag or error+next."""
    _check_site_key(x_site_key)
    return service.elementor_available()


@router.get("/elementor/posts/{post_id}")
def elementor_document(post_id: int, post_type: str = "posts",
                       x_site_key: str | None = Header(default=None)) -> dict:
    _check_site_key(x_site_key)
    return _resolve(service.elementor_document(post_id, post_type=post_type))


@router.post("/elementor/posts/{post_id}")
def elementor_save(post_id: int, body: ElementorSave,
                   x_site_key: str | None = Header(default=None)) -> dict:
    _check_site_key(x_site_key)
    return _resolve(service.elementor_save(post_id, body.elements,
                                           post_type=body.post_type,
                                           page_settings=body.page_settings))


@router.post("/elementor/articles/{article_id}/build")
def elementor_build(article_id: int, body: ElementorBuild | None = None,
                    x_site_key: str | None = Header(default=None)) -> dict:
    _check_site_key(x_site_key)
    result = service.elementor_build(article_id,
                                     post_id=(body.post_id if body else None),
                                     mode=(body.mode if body else "draft"))
    if "error" in result:
        if "not found" in result["error"] or "no content" in result["error"]:
            raise HTTPException(status_code=404, detail=result["error"])
        raise HTTPException(status_code=400, detail=result["error"])
    return result
