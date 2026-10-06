"""ContentFTE Phase 1 — Postgres (Neon) models + engine.

Spec: ContentFTE-Engine-Spec-v1 §5.16 (ledger), §5.1 (brand DNA),
§5.2 (audit), §5.10-6 (cost ledger), §5.14 (SEO cache).

Additive only — does NOT touch the model router / fallback chain
(blog_agent/custom_runner.py). Sheets stay the live store until the
cutover commit; this module is the new source of truth going forward.

Usage:
    DATABASE_URL=postgresql+psycopg://user:pass@host/db  (Neon)
    DATABASE_URL unset -> local sqlite ./contentfte.db (dev/test)
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        return url
    return "sqlite:///./contentfte.db"


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    site_type: Mapped[str] = mapped_column(String(40), default="custom")  # wordpress|custom|sanity
    base_url: Mapped[str] = mapped_column(String(500), default="")
    publish_mode: Mapped[str] = mapped_column(String(20), default="draft")  # draft|auto
    api_key: Mapped[str] = mapped_column(String(120), default="")
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class BrandProfile(Base):
    """§5.1 Brand DNA — versioned per site, auto-loaded at prompt level."""

    __tablename__ = "brand_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    profile: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    site: Mapped[Site] = relationship()


class KeywordLedger(Base):
    """§5.16 site keyword ledger (campaign memory)."""

    __tablename__ = "keyword_ledger"
    __table_args__ = (UniqueConstraint("site_id", "keyword", name="uq_site_keyword"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), nullable=False)
    keyword: Mapped[str] = mapped_column(String(300), nullable=False)
    intent: Mapped[str] = mapped_column(String(40), default="informational")
    volume: Mapped[int] = mapped_column(Integer, default=0)
    difficulty: Mapped[float] = mapped_column(Float, default=0.0)
    priority_score: Mapped[float] = mapped_column(Float, default=0.0)
    cluster_id: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(30), default="researched")
    target_url: Mapped[str] = mapped_column(String(500), default="")
    research_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    site: Mapped[Site] = relationship()


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), nullable=False)
    keyword_id: Mapped[int | None] = mapped_column(ForeignKey("keyword_ledger.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(500), default="")
    slug: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(30), default="drafted")
    scores: Mapped[dict] = mapped_column(JSON, default=dict)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    content_html: Mapped[str] = mapped_column(Text, default="")
    content_md: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    site: Mapped[Site] = relationship()


class CostLedger(Base):
    """§5.10-6 per-post cost ledger (LLM + images + data)."""

    __tablename__ = "cost_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)  # llm|image|data|total
    amount_usd: Mapped[float] = mapped_column(Float, default=0.0)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AuditLog(Base):
    """§5.2 every publish decision writes an audit row."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int | None] = mapped_column(ForeignKey("articles.id"), nullable=True)
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SeoCache(Base):
    """§5.14 30-day cache per keyword per provider."""

    __tablename__ = "seo_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    keyword: Mapped[str] = mapped_column(String(300), nullable=False)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ShareOfVoice(Base):
    """§5.8 / §24 monthly AI share-of-voice log.

    One row per (site, month, platform, prompt): whether the brand was cited
    in the answer. Aggregated into share-of-voice % per month — the Factory
    retainer report's proof metric."""

    __tablename__ = "share_of_voice"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), nullable=False)
    month: Mapped[str] = mapped_column(String(7), nullable=False)  # "YYYY-MM"
    platform: Mapped[str] = mapped_column(String(40), nullable=False)
    prompt: Mapped[str] = mapped_column(String(500), nullable=False)
    cited: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    site: Mapped[Site] = relationship()


_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        url = database_url()
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        _engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True)
    return _engine


def get_session():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _SessionLocal()


def init_db() -> None:
    Base.metadata.create_all(get_engine())
