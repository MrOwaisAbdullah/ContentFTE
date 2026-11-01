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

from lib.db import Article, AuditLog, KeywordLedger, get_session, init_db

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


def _stem(tok: str) -> str:
    """Tiny suffix stemmer so 'agents'/'agent', 'servers'/'server', 'building'/'build' compare equal.
    Deliberately crude and dependency-free; it only needs to be consistent on both sides."""
    if len(tok) > 4 and tok.endswith("ies"):
        return tok[:-3] + "y"
    if len(tok) > 5 and tok.endswith("ing"):
        return tok[:-3]
    if len(tok) > 3 and tok.endswith("s") and not tok.endswith(("ss", "us", "is")):
        return tok[:-1]
    return tok


_STOP = {"the", "a", "an", "and", "or", "for", "vs", "versus", "best", "top",
         "to", "of", "in", "on", "with", "how", "what", "is", "your", "guide"}


def _norm(text: str) -> set[str]:
    return {_stem(t) for t in re.findall(r"[a-z0-9]+", (text or "").lower())} - _STOP


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
            status="researched",
            research_snapshot=research_snapshot or {},
        )
        session.add(row)
    else:
        row.intent = intent
        row.volume = volume
        row.difficulty = difficulty
        row.priority_score = score
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


def overlap_ratio(candidate: set[str], existing: set[str]) -> float:
    """How strongly two keyword token sets compete (0 = unrelated, 1 = same topic).

    The old measure was |A∩B|/|A| only, which has two failure modes this fixes:
      * a one-word candidate matched ANY row containing that word (ratio 1.0);
      * a long-tail candidate that fully contains an existing head term looked unrelated
        (ratio < 0.6) even though the two pages would compete.
    Rules: at least two shared tokens (or identical sets); score = max(|A∩B|/|A|, Jaccard);
    and when the candidate fully covers the existing row, count that too, capped at 0.7 so it
    reads as 'differentiate' rather than 'merge'."""
    if not candidate or not existing:
        return 0.0
    inter = candidate & existing
    if not inter or (len(inter) < 2 and candidate != existing):
        return 0.0
    contain = len(inter) / len(candidate)
    jaccard = len(inter) / len(candidate | existing)
    reverse = min(len(inter) / len(existing), 0.7)
    return max(contain if contain >= 0.6 else 0.0,
               jaccard if jaccard >= 0.5 else 0.0,
               reverse if reverse >= 0.6 else 0.0)


def check_cannibalization(session: Session, site_id: int, candidate: str,
                          titles: "list[str] | None" = None) -> dict:
    """Intent-overlap guard before a keyword enters `approved`.

    Returns {overlap: bool, with_keyword: str|None, overlap_ratio: float, source: str}.
    Compared against every ledger row that is still competing for search traffic — including
    `won` (already ranking: the pages most worth protecting) — and against `titles`, the titles
    of articles that already exist on the site (many are not in the ledger at all).
    Threshold 0.6 → merge/differentiate, never two competing rows.
    """
    cand = _norm(candidate)
    if not cand:
        return {"overlap": False, "with_keyword": None, "overlap_ratio": 0.0, "source": ""}
    rows = session.execute(
        select(KeywordLedger).where(
            KeywordLedger.site_id == site_id, ~KeywordLedger.status.in_(["lost", "retired"])
        )
    ).scalars()
    best_text: str | None = None
    best_source = ""
    best_ratio = 0.0
    pool = [(row.keyword, "ledger") for row in rows] + [(t, "article") for t in (titles or []) if t]
    for text, source in pool:
        ratio = overlap_ratio(cand, _norm(text))
        if ratio > best_ratio:
            best_ratio, best_text, best_source = ratio, text, source
    if best_text is not None and best_ratio >= 0.6:
        return {"overlap": True, "with_keyword": best_text,
                "overlap_ratio": round(best_ratio, 3), "source": best_source}
    return {"overlap": False, "with_keyword": None,
            "overlap_ratio": round(best_ratio, 3), "source": ""}


def queue_health(session: Session, site_id: int) -> dict:
    """§5.16 guarantee the engine always has a 'work this next'.

    Returns {queue_size, has_next, next_keyword}. `has_next` False means the
    pipeline must research/approve more keywords before it can brief again."""
    rows = briefable_rows(session, site_id, limit=1000)
    nxt = next_keyword(session, site_id)
    return {
        "queue_size": len(rows),
        "has_next": nxt is not None,
        "next_keyword": nxt.keyword if nxt is not None else "",
        "priority_score": nxt.priority_score if nxt is not None else 0.0,
    }


def rotation_review(session: Session, site_id: int) -> dict:
    """30/60-day batch rotation ritual — writes a dated decision log per site."""
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
    report = {
        "reviewed_at": now.isoformat(),
        "site_id": site_id,
        "due_count": len(due),
        "due": [{"id": r.id, "keyword": r.keyword, "status": r.status} for r in due],
    }
    # Dated decision log: the ritual leaves a durable audit row per review.
    session.add(AuditLog(site_id=site_id, action="rotation_review", payload=report))
    session.commit()
    return report


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
