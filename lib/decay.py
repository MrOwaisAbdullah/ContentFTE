"""§5.10-1 GSC decay → refresh briefs (with §5.16 ranking write-back).

Pure Python: given per-page click totals for a current and a prior window
(plus optional signals), decide whether a page is decaying, whether the fix is
a **major** (republish new URL + 301) or **minor** (in-place + `dateModified`)
refresh, and build the refresh brief.

The live GSC pull lives in `scripts/decay_job.py`; keeping the decision logic
here makes it deterministic and testable without network. Thresholds come from
spec §5.10-1 (>30% click decay over 90 days) + playbook §7 (republish+301 for
major refreshes, in-place for minor).

Refresh briefs cite the tactics skill pack (`references/refresh-decay.md`).
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from lib.tactics import reference_path

# >30% click decay over the window triggers a refresh brief (spec §5.10-1).
DECAY_THRESHOLD = float(os.environ.get("DECAY_THRESHOLD") or "0.30")
# The comparison window; GSC's decay signal is measured over ~90 days.
DECAY_WINDOW_DAYS = int(os.environ.get("DECAY_WINDOW_DAYS") or "90")
# Deeper than this (or an intent shift / stale page) → major refresh.
MAJOR_REFRESH_THRESHOLD = float(os.environ.get("MAJOR_REFRESH_THRESHOLD") or "0.50")
STALE_DAYS = int(os.environ.get("REFRESH_STALE_DAYS") or "365")

# How a decaying page is refreshed (plan SEO-04 / decision D10):
#   escalate (default, the original behaviour) -- deep decay (>= MAJOR_REFRESH_THRESHOLD) or a page
#            older than REFRESH_STALE_DAYS gets a MAJOR refresh: republish under a NEW URL + 301.
#   in_place -- a decaying page is always refreshed in place (same URL, rewrite, bump dateModified).
#            MAJOR is reserved for an intent shift or a big quality gap, which are structural.
# Read at call time (not import) so it can be changed without restarting a long-lived process.
REFRESH_POLICIES = ("escalate", "in_place")


def refresh_policy() -> str:
    v = (os.environ.get("REFRESH_POLICY") or "escalate").strip().lower().replace("-", "_")
    return v if v in REFRESH_POLICIES else "escalate"

MAJOR = "major"
MINOR = "minor"
NONE = "none"

# Ordered action lists per mode — the operator/agent reads these top-to-bottom.
REFRESH_ACTIONS: Dict[str, List[str]] = {
    MAJOR: [
        "Improve the content (new angle, depth, and current data)",
        "Re-publish under a NEW URL",
        "301 redirect the old URL to the new one",
        "Bump dateModified (and the visible 'Updated' date)",
        "Repoint internal links from the old URL to the new URL",
        "Resubmit via IndexNow + Bing Webmaster Tools",
    ],
    MINOR: [
        "Update the page in place (keep the same URL)",
        "Bump dateModified (and the visible 'Updated' date)",
        "Resubmit via IndexNow + Bing Webmaster Tools",
    ],
}


def click_decay(current_clicks: Optional[float], prior_clicks: Optional[float]) -> Optional[float]:
    """Fractional click decay between two windows: (prior - current)/prior.

    Returns None when there is no usable baseline (prior <= 0) — a page with
    no prior traffic can't be said to have *decayed*."""
    try:
        prior = float(prior_clicks or 0)
        current = float(current_clicks or 0)
    except (TypeError, ValueError):
        return None
    if prior <= 0:
        return None
    return (prior - current) / prior


def is_seasonal(
    current_clicks: Optional[float],
    prior_clicks: Optional[float],
    last_year_current: Optional[float],
    last_year_prior: Optional[float],
    *,
    tolerance: float = 0.15,
    min_last_year_clicks: int = 10,
) -> bool:
    """True when this drop merely repeats LAST YEAR'S: the same two windows, a year earlier, fell by about the same
    fraction (within `tolerance`). A page whose traffic dips every winter is not decaying (SEO-16); refreshing it
    would burn effort and, worse, reset its URL history for a pattern the calendar explains.

    Needs a usable baseline last year (>= `min_last_year_clicks` in the earlier window); with none it says False -
    "unknown" must not hide a real decline."""
    this_year = click_decay(current_clicks, prior_clicks)
    last_year = click_decay(last_year_current, last_year_prior)
    if this_year is None or last_year is None:
        return False
    try:
        if float(last_year_prior or 0) < min_last_year_clicks:
            return False
    except (TypeError, ValueError):
        return False
    return this_year > 0 and last_year > 0 and abs(this_year - last_year) <= tolerance


def diagnose_cause(
    *,
    clicks_cur: float, clicks_prior: float,
    impressions_cur: float, impressions_prior: float,
    position_cur: Optional[float] = None, position_prior: Optional[float] = None,
) -> str:
    """Why did clicks fall? One of: rank | demand | ctr | mixed | unknown (SEO-16).

    * rank   - average position got worse by >= 1.5 places (a ranking loss: refresh content / links)
    * demand - impressions fell >= 25% with position steady (fewer searches: do not rewrite for it)
    * ctr    - impressions steady, position steady, but clicks/impression fell >= 25% (the SERP changed: an AI
               answer or feature took the click - a new title/meta or format, not a rewrite)
    The old job saw only 'clicks down' and prescribed the same refresh for all three."""
    try:
        imp_c, imp_p = float(impressions_cur), float(impressions_prior)
        if imp_p <= 0 or float(clicks_prior) <= 0:
            return "unknown"
        pos_worse = (position_cur is not None and position_prior is not None
                     and float(position_cur) - float(position_prior) >= 1.5)
        imp_drop = (imp_p - imp_c) / imp_p
        ctr_c = float(clicks_cur) / imp_c if imp_c > 0 else 0.0
        ctr_p = float(clicks_prior) / imp_p
        ctr_drop = (ctr_p - ctr_c) / ctr_p if ctr_p > 0 else 0.0
    except (TypeError, ValueError):
        return "unknown"
    causes = [c for c, hit in (("rank", pos_worse), ("demand", imp_drop >= 0.25 and not pos_worse),
                               ("ctr", ctr_drop >= 0.25 and imp_drop < 0.25 and not pos_worse)) if hit]
    if len(causes) == 1:
        return causes[0]
    return "mixed" if causes else "unknown"


def detect_decay(
    current_clicks: Optional[float],
    prior_clicks: Optional[float],
    threshold: float = DECAY_THRESHOLD,
) -> Dict[str, Any]:
    """Decide whether a single page is decaying past `threshold`."""
    decay = click_decay(current_clicks, prior_clicks)
    if decay is None:
        return {
            "decaying": False,
            "decay_pct": None,
            "reason": "no_baseline",
            "current_clicks": current_clicks,
            "prior_clicks": prior_clicks,
            "threshold": threshold,
        }
    return {
        "decaying": decay > threshold,
        "decay_pct": round(decay, 4),
        "reason": "decay" if decay > threshold else "stable",
        "current_clicks": current_clicks,
        "prior_clicks": prior_clicks,
        "threshold": threshold,
    }


def classify_refresh(
    decay_pct: Optional[float],
    *,
    intent_shift: bool = False,
    big_quality_gap: bool = False,
    age_days: Optional[int] = None,
    major_threshold: float = MAJOR_REFRESH_THRESHOLD,
    stale_days: int = STALE_DAYS,
) -> str:
    """major | minor | none.

    Force major on an intent shift or a big quality gap (playbook §7: those are
    always structural). Otherwise a decaying page is minor, escalating to major
    when the decay is deep or the page is stale -- unless REFRESH_POLICY=in_place,
    which keeps every non-structural refresh on the existing URL (a new URL + 301
    throws away the page's accumulated history, and a click drop can come from AI
    Overviews taking the click rather than from lost rank)."""
    if intent_shift or big_quality_gap:
        return MAJOR
    if decay_pct is None or decay_pct <= DECAY_THRESHOLD:
        return NONE
    if refresh_policy() == "in_place":
        return MINOR
    if decay_pct >= major_threshold or (age_days is not None and age_days >= stale_days):
        return MAJOR
    return MINOR


def build_refresh_brief(
    page_url: str,
    title: str,
    keyword: str,
    decay_pct: Optional[float],
    mode: str,
    addressable_queries: Optional[List[str]] = None,
    reason: str = "",
) -> Dict[str, Any]:
    """The refresh brief an operator/agent works from."""
    if mode not in (MAJOR, MINOR):
        raise ValueError(f"mode must be '{MAJOR}' or '{MINOR}', got {mode!r}")
    required = [
        "Refresh every date-sensitive statistic to a current, sourced value",
        "Add 2-3 new FAQ entries from current PAA / discourse data",
        "Update examples, tool versions, and screenshots to the present",
    ]
    required += (
        ["Re-publish under a new URL and 301 the old one"]
        if mode == MAJOR
        else ["Keep the same URL; update in place"]
    )
    return {
        "brief_type": "refresh",
        "mode": mode,
        "page_url": page_url,
        "title": title,
        "keyword": keyword,
        "decay_pct": decay_pct,
        "reason": reason,
        "actions": list(REFRESH_ACTIONS[mode]),
        "required_changes": required,
        "addressable_queries": list(addressable_queries or []),
        "reference": reference_path("refresh-decay"),
    }


def plan_refresh_briefs(
    pages: List[Dict[str, Any]],
    threshold: float = DECAY_THRESHOLD,
    major_threshold: float = MAJOR_REFRESH_THRESHOLD,
) -> List[Dict[str, Any]]:
    """Turn per-page metrics into refresh briefs (only for decaying pages).

    Each page dict: {url, title, keyword, current_clicks, prior_clicks,
    intent_shift?, big_quality_gap?, age_days?, addressable_queries?}.
    """
    briefs: List[Dict[str, Any]] = []
    for p in pages or []:
        det = detect_decay(p.get("current_clicks"), p.get("prior_clicks"), threshold)
        intent_shift = bool(p.get("intent_shift"))
        big_gap = bool(p.get("big_quality_gap"))
        if not det["decaying"] and not intent_shift and not big_gap:
            continue
        mode = classify_refresh(
            det["decay_pct"],
            intent_shift=intent_shift,
            big_quality_gap=big_gap,
            age_days=p.get("age_days"),
            major_threshold=major_threshold,
        )
        if mode == NONE:
            mode = MINOR  # decaying (or flagged) always yields at least a minor refresh
        briefs.append(
            build_refresh_brief(
                page_url=p.get("url", ""),
                title=p.get("title", ""),
                keyword=p.get("keyword", ""),
                decay_pct=det["decay_pct"],
                mode=mode,
                addressable_queries=p.get("addressable_queries"),
                reason=det["reason"] if det["decaying"] else "flagged",
            )
        )
    return briefs
