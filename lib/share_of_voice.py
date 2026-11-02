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


def wilson_interval(cited: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a citation rate, as percentages.

    One run per prompt per month is a very noisy sample (an LLM answer varies run to run), so a bare "23%" looks far
    more certain than it is. The interval says how much to trust a month-on-month move: if two months' intervals
    overlap, the 'trend' is probably noise (SEO-18)."""
    if total <= 0:
        return 0.0, 0.0
    p = cited / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * ((p * (1 - p) / total + z * z / (4 * total * total)) ** 0.5) / denom
    return round(100 * max(0.0, centre - half), 1), round(100 * min(1.0, centre + half), 1)


MIN_RUNS_FOR_CONFIDENCE = 30      # roughly 5 prompts x 3 samples x 2 platforms


def confidence_label(total: int) -> str:
    return "low" if total < MIN_RUNS_FOR_CONFIDENCE else ("medium" if total < 3 * MIN_RUNS_FOR_CONFIDENCE else "high")


def prompts_from_queries(queries: Iterable[str], category: str = "", limit: int = 10) -> List[str]:
    """Build the prompt set from what people really search (Search Console queries) instead of seven generic
    templates: question-form queries first, then the rest by the order given, de-duplicated, capped. Falls back to
    the scripted category prompts when there are no queries."""
    seen, questions, others = set(), [], []
    starters = ("how", "what", "why", "which", "when", "can", "is", "does", "should", "best", "vs")
    for q in queries or []:
        text = " ".join(str(q or "").split())
        key = text.lower()
        if len(text) < 6 or key in seen:
            continue
        seen.add(key)
        (questions if key.split(" ", 1)[0] in starters or key.endswith("?") else others).append(text)
    chosen = (questions + others)[: max(1, limit)]
    return chosen or category_prompts(category, count=min(limit, len(_PROMPT_TEMPLATES)))


def competitor_share(records: Iterable[Dict[str, Any]], top: int = 5) -> List[Dict[str, Any]]:
    """Who gets cited instead of you. Each record may carry `competitors: ["domain", ...]` (the other brands the
    answer named); returns [{name, cited_in, pct}] ranked, over the runs that carried the field."""
    counts: Dict[str, int] = {}
    runs = 0
    for r in records or []:
        comps = r.get("competitors")
        if comps is None:
            continue
        runs += 1
        for name in {str(c).strip().lower() for c in comps if str(c).strip()}:
            counts[name] = counts.get(name, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[: max(1, top)]
    return [{"name": n, "cited_in": c, "pct": share_of_voice_pct(c, runs)} for n, c in ranked]


def summarize(records: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate raw results into {overall_pct, by_month, by_platform}.

    Each record: {month: "YYYY-MM", platform, prompt, cited: bool}.
    """
    by_month: Dict[str, Dict[str, Any]] = {}
    by_platform: Dict[str, Dict[str, int]] = {}
    total = cited_total = 0
    records = list(records)
    by_prompt: Dict[tuple, List[bool]] = {}
    for r in records:
        by_prompt.setdefault((str(r.get("platform") or ""), str(r.get("prompt") or "")), []).append(bool(r.get("cited")))
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
    lo, hi = wilson_interval(cited_total, total)
    repeated = [v for v in by_prompt.values() if len(v) >= 2]
    # of the prompts sampled more than once, how many gave the SAME answer every time (a stable signal)?
    stable = sum(1 for v in repeated if len(set(v)) == 1)
    return {
        "overall_pct": share_of_voice_pct(cited_total, total),
        "ci95": [lo, hi],
        "confidence": confidence_label(total),
        "prompts": len(by_prompt),
        "repeated_prompts": len(repeated),
        "stable_repeated_pct": share_of_voice_pct(stable, len(repeated)) if repeated else None,
        "competitors": competitor_share(records),
        "runs": total,
        "by_month": {
            k: {"pct": share_of_voice_pct(v["cited"], v["total"]),
                "ci95": list(wilson_interval(v["cited"], v["total"])), **v}
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
