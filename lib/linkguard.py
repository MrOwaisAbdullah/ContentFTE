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
- ``path_key`` / ``page_depths`` / ``check_depth`` — site-graph click
  depth from the homepage (pack authority-internal: every important page
  ≤3 clicks from home)
- ``check_role_links`` — role rules (hub → BOFU; guides link 2-3 money
  pages)
"""
from __future__ import annotations

import re
from collections import deque
from typing import Dict, Iterable, List, Optional
from urllib.parse import urlparse

LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")


def path_key(url: str, base_url: str = "") -> str:
    """Canonical site-path key for graph lookups: returns only the path
    component after stripping host (same-site check against base_url), query
    and fragment, and trailing slash normalisation.  Returns ``""`` for
    external URLs (host differs from *base_url* or the URL cannot be parsed)
    or unusable strings."""
    if not isinstance(url, str):
        return ""
    text = url.strip()
    if not text or text.startswith(("#", "mailto:", "tel:", "javascript:")):
        return ""
    parsed = urlparse(text)
    if "://" in text or text.startswith("/"):
        host = parsed.hostname or ""
        if base_url:
            bhost = _url_host(base_url.rstrip("/")) or ""
            if bhost and host != bhost:
                return ""
        # keep path; lowercased for comparison — typical SERP URLs are lowercased
        # anyway, and this makes graph edges deterministic.
        path = (parsed.path or "/").lower()
        if len(path) > 1 and path.endswith("/"):
            path = path.rstrip("/")
        return path
    # no scheme and no leading "/" — treat as plain path (relative)
    text = text.lower().split("#", 1)[0].split("?", 1)[0]
    if not text or text == "/":
        return "/"
    if not text.startswith("/"):
        text = "/" + text
    if len(text) > 1 and text.endswith("/"):
        text = text.rstrip("/")
    return text


def _url_host(url: str) -> str:
    if url.startswith("/"):
        return ""
    parsed = urlparse(url)
    return (parsed.netloc or "").lower().removeprefix("www.")

# Roles that map onto the pack's hub / guide / money-page taxonomy.
_HUB_ROLES = ("hub", "hub-page", "pillar", "category")
_GUIDE_ROLES = ("guide", "guides", "listicle", "resource", "informational",
                "comparison")
_MONEY_ROLES = ("bofu", "money", "transactional", "landing", "service",
                "product")


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


def page_depths(home: str = "/", edges: Dict[str, List[str]] = None,
                *, root_depth: int = 2) -> Dict[str, int]:
    """Click-depth (from the homepage) over the internal link graph.

    ``edges`` maps a normalised page-path (source) to a list of target
    normalised paths.  ``home`` is the root path (e.g. ``"/"`` or
    ``"/blog"``).  ``root_depth`` is the assigned depth of any node whose
    indegree in the graph is zero and that is not reachable from *home* via
    the given edges.  Nodes unreachable from home or roots are omitted.

    Typical use: ``page_depths("/", edges_from_posts)`` — every published
    post becomes reachable from the blog index (depth ≈ 2); the function
    then propagates depths and flags pages whose minimum-click path from
    the homepage exceeds ``max_clicks`` (default 3) using
    :func:`check_depth`.

    Returns a dict mapping every reachable page to its minimum-click depth
    from the homepage.  Pages that are not reachable from *home* (and have
    no root path) are excluded entirely.
    """
    home = path_key(home) or "/"
    edges = edges or {}
    # normalise keys and targets
    norm: Dict[str, List[str]] = {}
    for src, targets in edges.items():
        s = path_key(src) or (home if src == "/" else "/")
        norm.setdefault(s, [])
        for t in targets:
            n = path_key(t) or "/"
            if n and n != s:
                norm[s].append(n)

    # indegree count (how many sources point at each node)
    all_nodes = set(list(norm.keys()) + [t for targets in norm.values() for t in targets])
    indeg: Dict[str, int] = {n: 0 for n in all_nodes}
    for src, targets in norm.items():
        for t in targets:
            indeg[t] = indeg.get(t, 0) + 1

    depths: Dict[str, int] = {home: 0}
    # BFS from home
    frontier = deque([home])
    while frontier:
        n = frontier.popleft()
        for t in norm.get(n, []):
            if t not in depths:
                depths[t] = depths[n] + 1
                frontier.append(t)

    # assign root_depth to indegree-zero nodes not yet assigned
    roots = [n for n, d in indeg.items() if d == 0 and n != home]
    for r in roots:
        depths[r] = root_depth
    # multi-source BFS (home + roots) — enqueue roots alongside home results
    all_frontier = deque(frontier)
    for r in roots:
        if r in depths:
            all_frontier.append(r)

    # standard BFS from combined queue (FIFO ensures minimum depth first)
    while all_frontier:
        n = all_frontier.popleft()
        for t in norm.get(n, []):
            if t not in depths:
                depths[t] = depths[n] + 1
                all_frontier.append(t)
            else:
                # already assigned; if a shorter path appears, update
                if depths[n] + 1 < depths[t]:
                    depths[t] = depths[n] + 1
                    all_frontier.append(t)

    # relaxation: any node still not assigned gets the minimum depth from
    # any assigned predecessor iteratively until fixpoint
    changed = True
    while changed:
        changed = False
        for n in all_nodes:
            if n in depths:
                continue
            # check if any predecessor has a known depth
            pred_depths = [depths[p] for p in norm if n in norm[p]]
            if pred_depths:
                min_pred = min(pred_depths)
                depths[n] = min_pred + 1
                changed = True
                all_frontier.append(n)

    # any nodes still absent after relaxation are unreachable and omitted
    return depths


def check_depth(page: str, depths: Dict[str, int], max_clicks: int = 3) -> Dict:
    """Whether *page* sits within ``max_clicks`` from the homepage.

    Returns a dict with keys ``page``, ``clicks``, ``known``, ``pass``,
    and ``guidance``.

    * ``clicks`` is the depth from the homepage as reported by
      :func:`page_depths`, or ``None`` when the page is not in the depth map.
    * ``known`` is ``True`` when a depth could be determined.
    * ``pass`` is ``True`` when the depth is ``≤ max_clicks`` (or when
      depth is unknown — fail-open so a sparse graph never blocks a draft).
    * ``guidance`` lists actionable notes (e.g. how to fix a deep page).
    """
    key = path_key(page) or (page if page == "/" else "")
    clicks = depths.get(key) if key else None
    if clicks is None:
        return {
            "page": key,
            "clicks": None,
            "known": False,
            "pass": True,
            "guidance": [],
        }
    ok = clicks <= max_clicks
    guidance = [] if ok else [
        f"'{page}' sits {clicks} clicks from the homepage "
        f"(max {max_clicks}) — link it from a hub page."
    ]
    return {
        "page": key,
        "clicks": clicks,
        "known": True,
        "pass": ok,
        "guidance": guidance,
    }


def check_role_links(
    page_role: str,
    internal_links: Iterable[Dict[str, str]],
    money_targets: Iterable[str] = (),
) -> Dict:
    """Role-specific internal-link rules (pack authority-internal).

    Rules enforced:
    - ``hub`` pages must link at least one BOFU/money page (hub → BOFU
      equity flow).  If *money_targets* are supplied and none of the
      linked targets match, ``pass`` is ``False`` with guidance.
    - ``guide``/``guides``/``listicle`` pages should link 2–3 money pages.
      If *money_targets* are supplied, the count of matched links must be
      within ``[2, 3]``; otherwise ``pass`` is ``False`` with guidance.
    - ``bofu``/``money``/``transactional``/``landing``/``service``/``product``
      pages: no rule (pass with ``rule = "none"``).
    - Unknown/empty role: pass with ``rule = "unknown"`` and no guidance.

    * ``money_targets`` may be a list of normalised paths (e.g.
      ``"/blog/pricing"``) or absolute URLs — each is canonicalised with
      ``path_key`` before matching.

    Returns a dict with keys ``pass``, ``role``, ``rule``,
    ``money_links`` (how many linked targets matched a money key),
    ``money_targets`` (how many distinct money keys exist), and
    ``guidance`` (fixes when ``pass`` is ``False``).
    """
    role = (page_role or "").strip().lower()
    links = list(internal_links)

    # Canonicalise every linked target to a path key
    link_keys = {path_key(l.get("url", "")) for l in links}
    link_keys.discard("")  # drop empties

    # Canonicalise money targets the same way
    money_keys = {path_key(t) for t in money_targets}

    count = sum(1 for k in link_keys if k in money_keys) if money_keys else 0

    if not role:
        return {
            "pass": True,
            "role": role,
            "rule": "unknown",
            "money_links": count,
            "money_targets": len(money_keys) if money_keys else 0,
            "guidance": [],
        }

    if role in _HUB_ROLES:
        if money_keys and count == 0:
            return {
                "pass": False,
                "role": role,
                "rule": "hub-no-money-link",
                "money_links": count,
                "money_targets": len(money_keys),
                "guidance": [
                    "hub page: link 1+ BOFU/money page(s) (hub → BOFU equity flow)."
                ],
            }
        return {
            "pass": True,
            "role": role,
            "rule": "hub-ok",
            "money_links": count,
            "money_targets": len(money_keys),
            "guidance": [],
        }

    if role in _GUIDE_ROLES:
        if not money_keys:
            return {
                "pass": True,
                "role": role,
                "rule": "insufficient_data",
                "money_links": count,
                "money_targets": len(money_keys),
                "guidance": [
                    "guides link 2–3 money pages — no money targets were "
                    "provided, so the check is inconclusive."
                ],
            }
        if count < 2:
            return {
                "pass": False,
                "role": role,
                "rule": "guide-too-few-money-links",
                "money_links": count,
                "money_targets": len(money_keys),
                "guidance": [
                    f"guides link 2–3 money pages (found {count}) — add "
                    f"{2 - count} more."
                ],
            }
        if count > 3:
            return {
                "pass": False,
                "role": role,
                "rule": "guide-too-many-money-links",
                "money_links": count,
                "money_targets": len(money_keys),
                "guidance": [
                    f"guides link 2–3 money pages (found {count}) — cap at "
                    f"3."
                ],
            }
        return {
            "pass": True,
            "role": role,
            "rule": "guide-ok",
            "money_links": count,
            "money_targets": len(money_keys),
            "guidance": [],
        }

    if role in _MONEY_ROLES:
        return {
            "pass": True,
            "role": role,
            "rule": "none",
            "money_links": count,
            "money_targets": len(money_keys),
            "guidance": [],
        }

    # any other role falls back to unknown
    return {
        "pass": True,
        "role": role,
        "rule": "unknown",
        "money_links": count,
        "money_targets": len(money_keys),
        "guidance": [],
    }
