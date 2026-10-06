"""§5.8 / §24 AI share-of-voice — monthly, per site.

Scripted category prompts are run against ChatGPT / Gemini / Perplexity /
AI Overviews / AI Mode; each run records whether the brand was cited. The
share-of-voice % per month is the Factory retainer report's proof metric.

Pure helpers (prompt set, pct, summarize) carry no I/O; the recorder writes
`share_of_voice` rows (lib/db). The actual prompt fan-out is operator-run in
Phase 1.5 (no vendor lock-in) — this module stores and aggregates the results.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from lib.db import ShareOfVoice, get_session, init_db

PLATFORMS = ["chatgpt", "gemini", "perplexity", "ai_overview", "ai_mode"]

_PROMPT_TEMPLATES = [
    "best {category} tools",
    "what is the best {category} software",
    "{category} tools for small business",
    "top {category} platforms",
    "how to choose a {category} tool",
    "{category} alternatives",
    "is {category} worth it",
]


def category_prompts(category: str, count: int = 5) -> List[str]:
    """The scripted category questions to run against each engine.

    Deterministic so the same month-to-month prompt set is comparable over
    time (the whole point of the metric is the trend)."""
    cat = (category or "").strip()
    return [t.format(category=cat) for t in _PROMPT_TEMPLATES[: max(1, count)]]


def share_of_voice_pct(cited: int, total: int) -> float:
    if not total:
        return 0.0
    return round(100.0 * cited / total, 1)


def summarize(records: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate raw results into {overall_pct, by_month, by_platform}.

    Each record: {month: "YYYY-MM", platform, prompt, cited: bool}.
    """
    by_month: Dict[str, Dict[str, Any]] = {}
    by_platform: Dict[str, Dict[str, int]] = {}
    total = cited_total = 0
    for r in records:
        month = str(r.get("month") or "")
        platform = str(r.get("platform") or "")
        cited = bool(r.get("cited"))
        total += 1
        cited_total += 1 if cited else 0
        m = by_month.setdefault(month, {"cited": 0, "total": 0})
        m["total"] += 1
        m["cited"] += 1 if cited else 0
        p = by_platform.setdefault(platform, {"cited": 0, "total": 0})
        p["total"] += 1
        p["cited"] += 1 if cited else 0
    return {
        "overall_pct": share_of_voice_pct(cited_total, total),
        "runs": total,
        "by_month": {
            k: {"pct": share_of_voice_pct(v["cited"], v["total"]), **v}
            for k, v in sorted(by_month.items())
        },
        "by_platform": {
            k: {"pct": share_of_voice_pct(v["cited"], v["total"]), **v}
            for k, v in sorted(by_platform.items())
        },
    }


def record_share_of_voice(
    session: Session,
    site_id: int,
    month: str,
    results: List[Dict[str, Any]],
) -> List[ShareOfVoice]:
    """Persist one month's prompt results. `results` items:
    {platform, prompt, cited: bool, position?: float|null}."""
    rows: List[ShareOfVoice] = []
    for r in results or []:
        row = ShareOfVoice(
            site_id=site_id,
            month=str(month),
            platform=str(r.get("platform") or ""),
            prompt=str(r.get("prompt") or ""),
            cited=bool(r.get("cited")),
            position=r.get("position"),
        )
        session.add(row)
        rows.append(row)
    session.commit()
    for row in rows:
        session.refresh(row)
    return rows


def load_summary(session: Session, site_id: int, month: Optional[str] = None) -> Dict[str, Any]:
    """Read stored rows and aggregate. `month` (YYYY-MM) optionally scopes."""
    q = select(ShareOfVoice).where(ShareOfVoice.site_id == site_id)
    if month:
        q = q.where(ShareOfVoice.month == month)
    rows = list(session.execute(q).scalars())
    return summarize([
        {"month": r.month, "platform": r.platform, "prompt": r.prompt, "cited": r.cited}
        for r in rows
    ])


def monthly_share_of_voice(month: str, results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Pure: summarize one month's results without touching the DB (for the
    operator's report before persisting)."""
    scoped = [dict(r, month=month) for r in results or []]
    return summarize(scoped)


def get_session_and_init() -> Session:
    init_db()
    return get_session()
