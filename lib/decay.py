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
    when the decay is deep or the page is stale."""
    if intent_shift or big_quality_gap:
        return MAJOR
    if decay_pct is None or decay_pct <= DECAY_THRESHOLD:
        return NONE
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
