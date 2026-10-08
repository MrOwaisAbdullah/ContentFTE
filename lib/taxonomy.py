"""§5.11 taxonomy derivation — categories + tags for a post (pure module).

The Article/SDK path never carries taxonomy in the brief (the driver and MCP
submit title-only briefs), so the push derives it instead of silently landing
on the site default category with zero tags. Precedence per field:

    categories: publisher brief/meta  ->  prefer-reuse lexical match against
    the site's EXISTING WP categories  ->  JEV Choice judge (when
    OPENROUTER_API_KEY is set: reuse an existing name, or judge a fresh one)
    ->  title-cased propose-new (also the JEV-unavailable fallback).

Anti-drift is the point: reuse beats invention, the deterministic lane runs
first (no latency), and the JEV lane only fires when lexical found nothing
confident — same rule the old sheet posting agent enforced via
`jev_classify_category`, but now at the service layer.

    tags: deterministic only (keyword/title phrase + salient tokens,
    stopwords stripped, capped at 5) — tags are cheap and numerous, so a
    judgment call adds cost without value.

I/O contract: only the optional JEV call does network I/O, it is env-gated
(OPENROUTER_API_KEY) and swallowed on any failure (returns None -> the
propose-new fallback), and tests inject `jev=` stubs directly. Never raises —
a degraded derivation must never block a publish.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

# Reuse an existing category at/above this token-overlap score without
# consulting JEV (1.0 = every category token appears in the topic).
LEXICAL_MIN_SCORE = 0.34
MAX_CATEGORIES = 3
MAX_TAGS = 5

_STOPWORDS = frozenset({
    # function words
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "for",
    "from", "has", "have", "how", "in", "into", "is", "it", "its", "of", "on",
    "or", "our", "that", "the", "their", "them", "there", "these", "they",
    "this", "to", "was", "we", "were", "what", "when", "which", "who", "why",
    "will", "with", "would", "you", "your",
    # comparison/listicle filler that never belongs in a tag
    "vs", "versus", "best", "top", "guide", "guides", "tutorial", "tutorials",
    "review", "reviews", "compared", "compare", "comparison", "alternatives",
    "alternative", "ultimate", "complete", "every", "need", "needs", "know",
    "make", "makes", "using", "used", "new", "good",
    # generic CMS nouns a title always carries
    "post", "posts", "blog", "blogs", "article", "articles", "page", "pages",
})


def _clean_phrase(text: Any = "") -> str:
    """Collapse whitespace, strip, cap at 60 chars (category/tag name length)."""
    phrase = re.sub(r"\s+", " ", str(text or "")).strip().strip("-+,.:;|")
    return phrase[:60].rstrip("-+,.:;| ") if phrase else ""


def _singular(token: str) -> str:
    """Light plural normalization so 'agents' matches 'agent'."""
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _tokens(text: str) -> set[str]:
    """Normalized token set: lowercased, singularized, stopwords/numerics/
    sub-2-char tokens dropped. Empty in -> empty out."""
    out: set[str] = set()
    for raw in re.findall(r"[a-z0-9]+", (text or "").lower()):
        if raw.isdigit() or len(raw) < 2 or raw in _STOPWORDS:
            continue
        out.add(_singular(raw))
    return out


def _as_list(value: Any) -> list[str]:
    """Brief/meta list field -> [str, ...] (tolerates a single string)."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v or "").strip()]


def _topic(keyword: str, title: str) -> str:
    """Matching context for lexical + JEV: the richer of keyword/title when
    one contains the other (titles usually repeat the keyword), else both."""
    kw, ti = _clean_phrase(keyword), _clean_phrase(title)
    if not kw:
        return ti
    if not ti:
        return kw
    kw_toks, ti_toks = _tokens(kw), _tokens(ti)
    if kw_toks and ti_toks and (kw_toks <= ti_toks or ti_toks <= kw_toks):
        return ti if len(ti) > len(kw) else kw
    return _clean_phrase(f"{kw} {ti}")


def _score(topic_toks: set[str], category_toks: set[str]) -> float:
    """0..1 overlap: full category containment scores 1.0 (a category whose
    every token appears in the topic reads as an exact fit), else Jaccard."""
    if not topic_toks or not category_toks:
        return 0.0
    if category_toks <= topic_toks:
        return 1.0
    inter = topic_toks & category_toks
    if not inter:
        return 0.0
    return len(inter) / len(topic_toks | category_toks)


def _lexical_match(topic: str, existing: list[str]) -> tuple[str, float]:
    """Best existing category for `topic`: highest score, then most specific
    (most tokens), then alphabetical. Returns ("", 0.0) on nothing useful."""
    topic_toks = _tokens(topic)
    best_name, best_key = "", (-1.0, -1, "")
    for name in existing:
        name = str(name or "").strip()
        if not name:
            continue
        cat_toks = _tokens(name)
        score = _score(topic_toks, cat_toks)
        key = (score, len(cat_toks), name.lower())
        if key > best_key:
            best_name, best_key = name, key
    if best_name == "":
        return "", 0.0
    return best_name, float(best_key[0])


def _propose_new(keyword: str, title: str) -> str:
    """Deterministic new category name from the keyword (else the title),
    title-cased to match the JEV fallback convention. '' when no topic."""
    phrase = _clean_phrase(keyword) or _clean_phrase(title)
    return phrase.title() if phrase else ""


def _jev_judge(topic: str, existing: list[str]) -> str | None:
    """JEV Choice judgment over the existing taxonomy — reuse an existing
    name or a judged-fresh one. Env-gated (OPENROUTER_API_KEY) and swallowed
    whole: JEV down/timeout/misconfigured returns None so the caller falls
    back to propose-new without ever blocking a publish. At most one JEV
    call per derivation (taxonomy is cached in article meta afterwards)."""
    if not existing:
        return None
    if not (os.environ.get("OPENROUTER_API_KEY") or "").strip():
        return None
    try:
        from lib.jev_tools import jev_classify_category
        parsed = json.loads(jev_classify_category(topic, json.dumps(existing[:255])))
    except Exception:  # noqa: BLE001 — judgment is optional
        return None
    name = str(parsed.get("category") or "").strip() if isinstance(parsed, dict) else ""
    return name or None


def derive_tags(*, keyword: str = "", title: str = "", brief: dict | None = None,
                max_tags: int = MAX_TAGS) -> list[str]:
    """Brief tags win; else the keyword phrase plus its salient tokens
    (title only when there is no keyword — titles carry generic CMS nouns).
    Stopwords/numerics dropped, case-insensitive dedupe, capped at max_tags."""
    supplied = _as_list((brief or {}).get("tags"))
    if supplied:
        return supplied[:max_tags]
    source = _clean_phrase(keyword) or _clean_phrase(title)
    if not source:
        return []
    tags: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        phrase = _clean_phrase(value)
        if not phrase or len(tags) >= max_tags:
            return
        key = phrase.lower()
        if key in seen or key in _STOPWORDS:
            return
        seen.add(key)
        tags.append(phrase)

    add(source)
    for raw in re.findall(r"[A-Za-z][A-Za-z0-9+-]{1,}", source):
        if raw.lower() in _STOPWORDS:
            continue
        add(raw)
    return tags


def resolve_category(*, keyword: str = "", title: str = "",
                     existing: list[str] | None = None,
                     jev=None) -> tuple[str, str]:
    """(category, source) with source in lexical|jev_reuse|jev_new|new.

    Precedence: prefer-reuse lexical >= LEXICAL_MIN_SCORE -> JEV judge ->
    title-cased propose-new. `jev` injects the judge (tests pass stubs;
    default resolves _jev_judge at call time so monkeypatch works)."""
    existing = [str(e).strip() for e in (existing or []) if str(e or "").strip()]
    if existing:
        topic = _topic(keyword, title)
        name, score = _lexical_match(topic, existing)
        if name and score >= LEXICAL_MIN_SCORE:
            return name, "lexical"
        judge = _jev_judge if jev is None else jev
        try:
            judged = judge(topic, existing)
        except Exception:  # noqa: BLE001 — judgment is optional
            judged = None
        if judged:
            judged = str(judged).strip()
            if any(judged.lower() == e.lower() for e in existing):
                return judged, "jev_reuse"
            return judged, "jev_new"
    proposed = _propose_new(keyword, title)
    return proposed, "new"


def derive_taxonomy(*, keyword: str = "", title: str = "", brief: dict | None = None,
                    meta: dict | None = None, existing_categories: list[str] | None = None,
                    jev=None) -> dict:
    """Full taxonomy for a post: publisher brief/meta wins per field, the
    other field derives independently. Never returns an empty category list
    when a topic exists (propose-new guarantees one)."""
    brief = brief if isinstance(brief, dict) else {}
    meta = meta if isinstance(meta, dict) else {}
    supplied_cats = _as_list(brief.get("categories"))
    cats_source = "brief"
    if not supplied_cats:
        supplied_cats = _as_list(meta.get("categories"))
        cats_source = "meta"
    if supplied_cats:
        categories = supplied_cats[:MAX_CATEGORIES]
    else:
        category, cats_source = resolve_category(
            keyword=keyword, title=title,
            existing=existing_categories, jev=jev)
        categories = [category] if category else []

    supplied_tags = _as_list(brief.get("tags"))
    tags_source = "brief"
    if not supplied_tags:
        supplied_tags = _as_list(meta.get("tags"))
        tags_source = "meta"
    if supplied_tags:
        tags = supplied_tags[:MAX_TAGS]
    else:
        tags = derive_tags(keyword=keyword, title=title, brief=None)
        tags_source = "derived"

    return {
        "categories": categories,
        "tags": tags,
        "category_source": cats_source,
        "tag_source": tags_source,
    }
