"""§5.16 Site keyword ledger — lifecycle, priority queue, rotation.

Statuses: researched → approved → queued → briefed → drafted →
published → ranking → won | lost | retired

Rules enforced here (pure Python, no LLM calls so the model router is
untouched):
- brief may only pull from approved/queued rows
- priority_score = (volume × intent_value × winnability) / difficulty
- cannibalization guard: normalized overlap vs non-retired rows
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from lib.db import Article, KeywordLedger, get_session, init_db

VALID_STATUSES = {
    "researched",
    "approved",
    "queued",
    "briefed",
    "drafted",
    "published",
    "ranking",
    "won",
    "lost",
    "retired",
}

INTENT_VALUE = {
    "transactional": 3.0,
    "commercial": 2.0,
    "local": 2.0,
    "informational": 1.0,
    "navigational": 0.8,
}

TERMINAL = {"won", "lost", "retired"}


def _norm(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (text or "").lower())) - {
        "the", "a", "an", "and", "or", "for", "vs", "versus", "best", "top",
    }


def priority_score(volume: int, intent: str, difficulty: float, winnability: float = 0.5) -> float:
    """Spec §5.16 priority formula. difficulty<=0 treated as 1 (unknown)."""
    intent_value = INTENT_VALUE.get((intent or "").lower(), 1.0)
    denom = difficulty if difficulty and difficulty > 0 else 1.0
    return (max(volume, 0) * intent_value * max(min(winnability, 1.0), 0.0)) / denom


def upsert_keyword(
    session: Session,
    site_id: int,
    keyword: str,
    intent: str = "informational",
    volume: int = 0,
    difficulty: float = 0.0,
    winnability: float = 0.5,
    cluster_id: str = "",
    research_snapshot: dict | None = None,
) -> KeywordLedger:
    keyword = keyword.strip()
    score = priority_score(volume, intent, difficulty, winnability)
    row = session.execute(
        select(KeywordLedger).where(
            KeywordLedger.site_id == site_id, KeywordLedger.keyword == keyword
        )
    ).scalar_one_or_none()
    if row is None:
        row = KeywordLedger(
            site_id=site_id,
            keyword=keyword,
            intent=intent,
            volume=volume,
            difficulty=difficulty,
            priority_score=score,
            cluster_id=cluster_id,
            status="researched",
            research_snapshot=research_snapshot or {},
        )
        session.add(row)
    else:
        row.intent = intent
        row.volume = volume
        row.difficulty = difficulty
        row.priority_score = score
        if cluster_id:
            row.cluster_id = cluster_id
        if research_snapshot:
            row.research_snapshot = research_snapshot
    session.commit()
    session.refresh(row)
    return row


def set_status(session: Session, row_id: int, status: str) -> KeywordLedger:
    if status not in VALID_STATUSES:
        raise ValueError(f"unknown ledger status: {status}")
    row = session.get(KeywordLedger, row_id)
    if row is None:
        raise ValueError(f"ledger row {row_id} not found")
    row.status = status
    session.commit()
    session.refresh(row)
    return row


def next_keyword(session: Session, site_id: int) -> KeywordLedger | None:
    """Highest priority approved/queued row — the engine's 'work this next'."""
    return session.execute(
        select(KeywordLedger)
        .where(KeywordLedger.site_id == site_id, KeywordLedger.status.in_(["approved", "queued"]))
        .order_by(KeywordLedger.priority_score.desc(), KeywordLedger.added_at.asc())
        .limit(1)
    ).scalar_one_or_none()


def briefable_rows(session: Session, site_id: int, limit: int = 20) -> list[KeywordLedger]:
    """Brief agent may ONLY pull from these rows. No keyword, no brief."""
    return list(
        session.execute(
            select(KeywordLedger)
            .where(KeywordLedger.site_id == site_id, KeywordLedger.status.in_(["approved", "queued"]))
            .order_by(KeywordLedger.priority_score.desc())
            .limit(limit)
        ).scalars()
    )


def check_cannibalization(session: Session, site_id: int, candidate: str) -> dict:
    """Intent-overlap guard before a keyword enters `approved`.

    Returns {overlap: bool, with_keyword: str|None, overlap_ratio: float}.
    overlap_ratio = |intersection| / |candidate tokens| over non-retired rows.
    Threshold 0.6 → merge/differentiate, never two competing rows.
    """
    cand = _norm(candidate)
    if not cand:
        return {"overlap": False, "with_keyword": None, "overlap_ratio": 0.0}
    rows = session.execute(
        select(KeywordLedger).where(
            KeywordLedger.site_id == site_id, ~KeywordLedger.status.in_(list(TERMINAL))
        )
    ).scalars()
    best: KeywordLedger | None = None
    best_ratio = 0.0
    for row in rows:
        tokens = _norm(row.keyword)
        if not tokens:
            continue
        ratio = len(cand & tokens) / len(cand)
        if ratio > best_ratio:
            best_ratio = ratio
            best = row
    if best is not None and best_ratio >= 0.6:
        return {"overlap": True, "with_keyword": best.keyword, "overlap_ratio": round(best_ratio, 3)}
    return {"overlap": False, "with_keyword": None, "overlap_ratio": round(best_ratio, 3)}


def cluster_coverage(session: Session, site_id: int, cluster_id: str) -> dict:
    rows = list(
        session.execute(
            select(KeywordLedger).where(
                KeywordLedger.site_id == site_id, KeywordLedger.cluster_id == cluster_id
            )
        ).scalars()
    )
    if not rows:
        return {"total": 0, "published": 0, "coverage_pct": 0.0}
    published = sum(1 for r in rows if r.status in {"published", "ranking", "won"})
    return {
        "total": len(rows),
        "published": published,
        "coverage_pct": round(100.0 * published / len(rows), 1),
    }


def rotation_review(session: Session, site_id: int) -> dict:
    """30/60-day batch rotation ritual — dated decision log per site."""
    now = datetime.now(timezone.utc)
    due = list(
        session.execute(
            select(KeywordLedger).where(
                KeywordLedger.site_id == site_id,
                KeywordLedger.review_at.is_not(None),
                KeywordLedger.review_at <= now,
                ~KeywordLedger.status.in_(list(TERMINAL)),
            )
        ).scalars()
    )
    return {
        "reviewed_at": now.isoformat(),
        "site_id": site_id,
        "due_count": len(due),
        "due": [{"id": r.id, "keyword": r.keyword, "status": r.status} for r in due],
    }


def link_article(session: Session, article_id: int, keyword_id: int) -> Article:
    """Article lineage: every article references its keyword_id + snapshot."""
    article = session.get(Article, article_id)
    keyword = session.get(KeywordLedger, keyword_id)
    if article is None or keyword is None:
        raise ValueError("article or keyword not found")
    article.keyword_id = keyword.id
    article.meta = {**(article.meta or {}), "research_snapshot": keyword.research_snapshot}
    session.commit()
    session.refresh(article)
    return article


def get_session_and_init() -> Session:
    init_db()
    return get_session()
