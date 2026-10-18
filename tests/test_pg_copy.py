"""Whole-store copy (scripts/copy_sqlite_to_postgres.py) — the Postgres
switch migration.

Runs source and target as two sqlite files so every behavior — id
preservation, FK-safe order, idempotent re-run, update propagation, dry-run,
sequence-reset guard — is covered without a live Postgres. The actual PG
runtime path (copy + engine service ops) is exercised by
tests/test_postgres_smoke.py when TEST_PG_URL is set.
"""
from __future__ import annotations

import os

from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

from lib.db import (
    Article,
    AuditLog,
    Base,
    BrandProfile,
    CostLedger,
    KeywordLedger,
    ShareOfVoice,
    Site,
    TavilyUsage,
)
from scripts.copy_sqlite_to_postgres import copy_store


def _url(tmp_path, name: str) -> str:
    return f"sqlite:///{(tmp_path / name).as_posix()}"


def _seed(url: str) -> dict:
    """One row per table, with FK links that must survive the copy."""
    eng = create_engine(url)
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        site = Site(slug="copy-src", name="Copy Source", site_type="custom",
                    base_url="https://copy.test", settings={"lang": "en"})
        s.add(site)
        s.flush()
        s.add(BrandProfile(site_id=site.id, profile={"tone": "plain"}))
        kw = KeywordLedger(site_id=site.id, keyword="copy keyword",
                           status="approved",
                           research_snapshot={"sources": 2})
        s.add(kw)
        s.flush()
        art = Article(site_id=site.id, keyword_id=kw.id, title="Copy me",
                      slug="copy-me", status="generated", cost_usd=0.02,
                      scores={"seo": 8.5}, content_md="# Copy me\n\nBody.",
                      meta={"brief": {"description": "d"},
                            "images": [{"slot": "featured", "path": "x.jpg"}]})
        s.add(art)
        s.flush()
        s.add_all([
            CostLedger(article_id=art.id, kind="llm", amount_usd=0.0123,
                       detail={"model": "gemini"}),
            AuditLog(article_id=art.id, site_id=site.id,
                     action="article.generate",
                     payload={"ok": True, "n": 3}),
            TavilyUsage(site_id=site.id, month="2026-10", calls=4),
            ShareOfVoice(site_id=site.id, month="2026-10", platform="chatgpt",
                         prompt="best seo agent", cited=True, position=2.0),
        ])
        s.commit()
        ids = {"site": site.id, "kw": kw.id, "art": art.id}
    eng.dispose()
    return ids


def _counts(url: str) -> dict:
    eng = create_engine(url)
    try:
        with Session(eng) as s:
            return {
                "sites": s.scalar(select(func.count()).select_from(Site)),
                "brand_profiles": s.scalar(select(func.count()).select_from(BrandProfile)),
                "keyword_ledger": s.scalar(select(func.count()).select_from(KeywordLedger)),
                "articles": s.scalar(select(func.count()).select_from(Article)),
                "cost_ledger": s.scalar(select(func.count()).select_from(CostLedger)),
                "audit_log": s.scalar(select(func.count()).select_from(AuditLog)),
                "share_of_voice": s.scalar(select(func.count()).select_from(ShareOfVoice)),
                "tavily_usage": s.scalar(select(func.count()).select_from(TavilyUsage)),
            }
    finally:
        eng.dispose()


def test_copy_preserves_ids_links_and_values(tmp_path):
    src_url, dst_url = _url(tmp_path, "src.db"), _url(tmp_path, "dst.db")
    ids = _seed(src_url)

    report = copy_store(src_url, dst_url, log=lambda *_: None)

    assert report["dry_run"] is False
    # sqlite target: no identity sequences, so the reset is a Postgres-only
    # step and must be skipped cleanly.
    assert report["sequences_reset"] is False
    assert {k: v["written"] for k, v in report["tables"].items()} == {
        "sites": 1, "brand_profiles": 1, "keyword_ledger": 1, "articles": 1,
        "cost_ledger": 1, "audit_log": 1, "seo_cache": 0,
        "share_of_voice": 1, "tavily_usage": 1,
    }

    eng = create_engine(dst_url)
    try:
        with Session(eng) as s:
            site = s.get(Site, ids["site"])
            assert site is not None and site.settings == {"lang": "en"}
            kw = s.get(KeywordLedger, ids["kw"])
            assert kw is not None and kw.research_snapshot == {"sources": 2}
            art = s.get(Article, ids["art"])
            assert art is not None and art.keyword_id == ids["kw"]
            assert art.meta["images"][0]["path"] == "x.jpg"
            cost = s.execute(select(CostLedger)).scalars().one()
            assert cost.article_id == ids["art"] and cost.amount_usd == 0.0123
            audit = s.execute(select(AuditLog)).scalars().one()
            assert audit.payload == {"ok": True, "n": 3}
            usage = s.execute(select(TavilyUsage)).scalars().one()
            assert usage.calls == 4
            sov = s.execute(select(ShareOfVoice)).scalars().one()
            assert sov.cited is True and sov.position == 2.0
    finally:
        eng.dispose()


def test_rerun_is_idempotent_and_propagates_edits(tmp_path):
    src_url, dst_url = _url(tmp_path, "src.db"), _url(tmp_path, "dst.db")
    _seed(src_url)
    copy_store(src_url, dst_url, log=lambda *_: None)
    before = _counts(dst_url)

    # Edit the source, copy again: values update, no duplicated rows.
    eng = create_engine(src_url)
    try:
        with Session(eng) as s:
            art = s.execute(select(Article)).scalars().one()
            art.title = "Copy me (edited)"
            s.commit()
    finally:
        eng.dispose()
    copy_store(src_url, dst_url, log=lambda *_: None)

    assert _counts(dst_url) == before
    eng = create_engine(dst_url)
    try:
        with Session(eng) as s:
            assert s.execute(select(Article)).scalars().one().title == "Copy me (edited)"
    finally:
        eng.dispose()


def test_dry_run_writes_nothing(tmp_path):
    src_url = _url(tmp_path, "src.db")
    dst_path = tmp_path / "dst.db"
    _seed(src_url)

    report = copy_store(src_url, _url(tmp_path, "dst.db"), dry_run=True,
                        log=lambda *_: None)

    assert report["dry_run"] is True
    assert report["tables"]["articles"]["read"] == 1
    assert report["tables"]["articles"]["written"] == 0
    # The target was never opened — no file, no schema.
    assert not os.path.exists(dst_path)


def test_orphan_fk_rows_are_nulled_or_skipped(tmp_path):
    """SQLite doesn't enforce FKs, so deleting an article leaves orphan
    cost/audit rows behind. The copy must handle them instead of dying on
    Postgres' enforced FK: a nullable FK (audit_log.article_id) is set to
    NULL and the row is kept; a non-nullable FK (cost_ledger.article_id)
    drops the row. Both cases land in report["orphans"]."""
    src_url, dst_url = _url(tmp_path, "src.db"), _url(tmp_path, "dst.db")
    ids = _seed(src_url)
    eng = create_engine(src_url)
    try:
        with Session(eng) as s:
            # Raw DELETE — sqlite lets the cost/audit rows dangle.
            s.execute(delete(Article))
            s.commit()
    finally:
        eng.dispose()

    report = copy_store(src_url, dst_url, log=lambda *_: None)

    # Non-nullable orphan dropped, nullable orphan nulled + kept.
    assert report["tables"]["cost_ledger"] == {"read": 1, "written": 0}
    assert report["tables"]["audit_log"] == {"read": 1, "written": 1}
    assert {(o["table"], o["column"], o["action"], o["value"])
            for o in report["orphans"]} == {
        ("cost_ledger", "article_id", "skipped", ids["art"]),
        ("audit_log", "article_id", "nulled", ids["art"]),
    }

    eng = create_engine(dst_url)
    try:
        with Session(eng) as s:
            assert s.scalar(select(func.count()).select_from(CostLedger)) == 0
            audit = s.execute(select(AuditLog)).scalars().one()
            # The audit row survived with its broken link cleared, and its
            # still-valid site link untouched.
            assert audit.article_id is None
            assert audit.site_id == ids["site"]
    finally:
        eng.dispose()
