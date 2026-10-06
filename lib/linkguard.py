"""Phase 1 §5.6 internal-link hardening — pure helpers.

Deterministic, no-network checks and orderings used by the draft agent's
link tools:

- ``extract_links`` / ``classify_links`` — markdown link inventory
- ``check_hygiene`` — 3-8 internal links/article + anchor diversity
  (no exact-match anchor repeated more than twice)
- ``inbound_counts`` — how many other posts link to each candidate
  (orphan rescue: pages with <3 inbound links get preference)
- ``rescue_order`` — reorder candidates so needy pages come first
  while staying stable within equal inbound counts
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional
from urllib.parse import urlparse

LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")


def extract_links(markdown: str) -> List[Dict[str, str]]:
    """Return ``[{"text": anchor, "url": href}, ...]`` for markdown links."""
    if not markdown:
        return []
    return [
        {"text": match.group(1).strip(), "url": match.group(2).strip()}
        for match in LINK_RE.finditer(markdown)
    ]


def _url_host(url: str) -> str:
    if url.startswith("/"):
        return ""
    parsed = urlparse(url)
    return (parsed.netloc or "").lower().removeprefix("www.")


def classify_links(
    links: Iterable[Dict[str, str]], base_url: str = ""
) -> Dict[str, List[Dict[str, str]]]:
    """Split links into ``internal`` vs ``external``.

    Internal = relative path, shares the ``base_url`` host, or (when no
    base_url given) a path-only/localhost URL that clearly isn't a
    third-party domain guess.
    """
    base_host = _url_host(base_url.rstrip("/")) if base_url else ""
    internal: List[Dict[str, str]] = []
    external: List[Dict[str, str]] = []
    for link in links:
        url = link.get("url", "")
        host = _url_host(url)
        if not host:
            internal.append(link)
        elif base_host and host == base_host:
            internal.append(link)
        elif not base_host and url.startswith("/"):
            internal.append(link)
        else:
            external.append(link)
    return {"internal": internal, "external": external}


def check_hygiene(
    markdown: str,
    base_url: str = "",
    min_internal: int = 3,
    max_internal: int = 8,
    max_exact_anchor: int = 2,
    min_external: int = 1,
    max_external: int = 3,
) -> Dict:
    """Spec §5.6 link hygiene report.

    Returns a dict with ``pass`` (bool), counts, duplicate anchors and
    ``guidance`` (actionable fixes for the generator). ``pass`` enforces:
    internal count within [min_internal, max_internal], external within
    [min_external, max_external], and no exact-match anchor repeated
    more than ``max_exact_anchor`` times.
    """
    links = extract_links(markdown or "")
    classified = classify_links(links, base_url=base_url)
    internal = classified["internal"]
    external = classified["external"]

    anchor_counts: Dict[str, int] = {}
    for link in internal + external:
        key = link["text"].lower()
        if key:
            anchor_counts[key] = anchor_counts.get(key, 0) + 1
    duplicates = {
        anchor: count
        for anchor, count in sorted(anchor_counts.items())
        if count > max_exact_anchor
    }

    problems: List[str] = []
    if len(internal) < min_internal:
        problems.append(
            f"{len(internal)} internal links found; spec requires "
            f"{min_internal}-{max_internal} per article (link every "
            "relevant existing post if the site has fewer)."
        )
    elif len(internal) > max_internal:
        problems.append(
            f"{len(internal)} internal links found; spec caps at "
            f"{max_internal} — drop the weakest ones."
        )
    if len(external) < min_external:
        problems.append(
            f"{len(external)} external links found; at least "
            f"{min_external} citation is required for E-E-A-T."
        )
    elif len(external) > max_external:
        problems.append(
            f"{len(external)} external links found; cap is {max_external}."
        )
    if duplicates:
        problems.append(
            "anchor diversity: these exact-match anchors repeat more "
            f"than {max_exact_anchor}x: "
            + ", ".join(f'"{a}" x{n}' for a, n in duplicates.items())
            + " — rewrite the repeats with varied anchor text."
        )

    return {
        "pass": not problems,
        "internal_count": len(internal),
        "external_count": len(external),
        "duplicate_anchors": duplicates,
        "guidance": problems,
    }


def inbound_counts(
    source_hrefs: Dict[str, List[str]],
    target_slugs: Iterable[str],
    self_slug: Optional[str] = None,
) -> Dict[str, int]:
    """Count inbound links per candidate slug.

    ``source_hrefs`` maps a source post's slug path (e.g. ``"/blog/x"``)
    to every outbound href found in its ``content[].markDefs[].href``.
    A target counts a hit when a *different* post's href contains the
    target's slug path (``/blog/<slug>``), regardless of host — authors
    link with full URLs. ``self_slug`` links are ignored (a post never
    counts as its own inbound).
    """
    counts: Dict[str, int] = {}
    for slug in target_slugs:
        if not slug:
            continue
        bare = slug.split("/blog/")[-1].strip("/")
        needle = f"/blog/{bare}"
        total = 0
        for source, hrefs in source_hrefs.items():
            if self_slug and source.rstrip("/") == self_slug.rstrip("/"):
                continue
            for href in hrefs or []:
                if needle and needle in href:
                    total += 1
                    break
        counts[slug] = total
    return counts


def rescue_order(
    candidates: List[Dict], inbound: Dict[str, int]
) -> List[Dict]:
    """Orphan rescue ordering (§5.6): pages with <3 inbound links first,
    ascending, then the already-ordered tail (recency) — stable sort so
    equal-inbound candidates keep their original (newest-first) order.
    """
    def key(candidate: Dict) -> int:
        slug = candidate.get("slug", "")
        count = inbound.get(slug, 0)
        return count if count < 3 else 3

    return sorted(candidates, key=key)
