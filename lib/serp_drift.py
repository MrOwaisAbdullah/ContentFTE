"""§5.16 SERP snapshots & drift alerts — pure comparison logic.

The monthly drift job (scripts/serp_drift_job.py) compares a keyword's
brief-time top-10 (SeoCache baseline) against a force-refreshed SERP:
when less than `min_overlap` of the baseline URLs are still present, the
intent/results shifted and the page needs a refresh brief (pack:
refresh / share-of-voice "drift = top-10 churn"). No DB, no network —
injectable inputs so it is trivially testable.
"""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

# Below this share of baseline URLs still present, results are treated
# as drifted (pack refresh guidance: ~40%+ churn means re-research).
DEFAULT_MIN_OVERLAP = 0.4
_TRACKING_KEYS = ("utm_", "gclid", "fbclid", "msclkid")


def normalize_url(url: str) -> str:
    """Canonical form for overlap comparison: https, host lowercased with
    leading www. stripped, trailing slash dropped, tracking params
    removed, fragment dropped. Empty string when unusable."""
    if not isinstance(url, str):
        return ""
    text = url.strip()
    if not text:
        return ""
    if "://" not in text:
        text = "https://" + text
    try:
        parts = urlparse(text)
    except ValueError:
        return ""
    # scheme + hostname lowercase (urlparse already lowercases both);
    # path case is preserved — paths can be case-sensitive.
    host = (parts.hostname or "").lower().strip(".")
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return ""
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query)
                       if not k.lower().startswith(_TRACKING_KEYS)])
    return urlunparse(("https", host, path, "", query, ""))


def serp_urls(serp) -> list[str]:
    """Normalized URL list out of a provider `serp` payload: entries may be
    plain URL strings or dicts (url/link/href/page_url). Deduped,
    order-preserving; unusable entries are dropped."""
    out: list[str] = []
    for entry in serp or []:
        if isinstance(entry, str):
            raw = entry
        elif isinstance(entry, dict):
            raw = (entry.get("url") or entry.get("link")
                   or entry.get("href") or entry.get("page_url") or "")
        else:
            continue
        norm = normalize_url(str(raw))
        if norm and norm not in out:
            out.append(norm)
    return out


def detect_drift(baseline_urls: list[str], fresh_urls: list[str],
                 *, min_overlap: float = DEFAULT_MIN_OVERLAP) -> dict:
    """Compare a baseline top-N against a fresh top-N.

    `overlap_score` = share of baseline URLs still present in the fresh
    set; `drifted` when that drops below `min_overlap`. No baseline →
    not drifted (no signal to act on)."""
    base = [u for u in dict.fromkeys(
        normalize_url(str(u)) for u in (baseline_urls or [])) if u]
    fresh = [u for u in dict.fromkeys(
        normalize_url(str(u)) for u in (fresh_urls or [])) if u]
    fresh_set = set(fresh)
    kept = [u for u in base if u in fresh_set]
    dropped = [u for u in base if u not in fresh_set]
    added = [u for u in fresh if u not in set(base)]
    score = (len(kept) / len(base)) if base else 0.0
    return {
        "baseline_count": len(base),
        "fresh_count": len(fresh),
        "overlap": len(kept),
        "overlap_score": round(score, 3),
        "churn": round(1.0 - score, 3) if base else 0.0,
        "dropped": dropped,
        "new": added,
        "drifted": bool(base) and score < min_overlap,
        "min_overlap": float(min_overlap),
    }
