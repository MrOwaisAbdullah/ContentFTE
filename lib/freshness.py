"""Honest `dateModified` (plan SEO-08 / SEO-19).

Two defects: the engine passed the *publish* date as `dateModified` (so it never
differed from `datePublished`, and Google/AI engines never saw a refresh), and the
refresh playbook said to "bump dateModified" unconditionally — which Google lists as
a warning sign when the page didn't materially change.

So: record `meta["modified_at"]` only when the text changed *substantively*, and report
that as `dateModified`. Pure functions, no I/O.
"""
from __future__ import annotations

import difflib
import re
from datetime import datetime, timezone
from typing import Any, Optional

# Share of the article's words that must differ before an edit counts as a real update.
# Fixing a typo or reflowing whitespace is not a content update.
MIN_CHANGE_RATIO = 0.03

_WORD_RE = re.compile(r"[\w'’-]+")


def _words(text: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text or "")]


def change_ratio(old: str, new: str) -> float:
    """0.0 (identical words) .. 1.0 (nothing in common), at word level."""
    a, b = _words(old), _words(new)
    if not a and not b:
        return 0.0
    return 1.0 - difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def substantive_change(old: str, new: str, min_ratio: float = MIN_CHANGE_RATIO) -> bool:
    return change_ratio(old, new) >= min_ratio


def bump_modified(meta: dict, old_text: str, new_text: str, *, now: Optional[datetime] = None) -> dict:
    """Return `meta` (a copy) with `modified_at` set to now iff the edit was substantive."""
    out = dict(meta or {})
    if substantive_change(old_text, new_text):
        out["modified_at"] = (now or datetime.now(timezone.utc)).isoformat()
    return out


def effective_modified(meta: Any, published_at: Optional[str], created_at: Optional[str]) -> Optional[str]:
    """`modified_at` if the content was ever substantively updated, else the publish date,
    else creation. Never earlier than the publish date."""
    m = (meta or {}).get("modified_at") if isinstance(meta, dict) else None
    base = published_at or created_at
    if m and base and str(m) < str(base):
        return base
    return m or base
