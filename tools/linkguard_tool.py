"""Draft-agent link tools — §5.6 internal-link hardening.

Plain functions (unit-testable) + ``@function_tool`` wrappers registered
on the generator agent:

- ``check_link_hygiene_tool``  — deterministic 3-8 links/article +
  anchor-diversity check, run before the draft is returned.
- ``fetch_rescue_links_tool``  — same candidates as
  ``fetch_internal_links_tool`` but ordered orphan-first (posts with
  fewer than 3 inbound links come first) with an ``inbound`` count
  attached to each.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from agents import function_tool

from lib.linkguard import check_hygiene, inbound_counts, rescue_order


def check_link_hygiene(
    draft_markdown: str,
    base_url: str = "",
) -> Dict[str, Any]:
    """Pure hygiene check over the draft markdown (no network)."""
    if not isinstance(draft_markdown, str) or not draft_markdown.strip():
        return {
            "status": "error",
            "pass": False,
            "guidance": ["draft_markdown must be a non-empty string."],
        }
    report = check_hygiene(draft_markdown, base_url=base_url)
    return {"status": "ok", **report}


def _build_adapter():
    from lib.sanity_adapter import SanityAdapter

    return SanityAdapter(
        project_id=os.environ["SANITY_PROJECT_ID"],
        dataset=os.environ.get("SANITY_DATASET") or "production",
        token=os.environ["SANITY_API_TOKEN"],
    )


def _fetch_all_hrefs(adapter) -> Dict[str, List[str]]:
    """Map every post's slug path to its outbound hrefs (content links)."""
    query = (
        '*[_type == "post"]{'
        '"slugPath": "/blog/" + slug.current, '
        'hrefs: content[].markDefs[].href}'
    )
    endpoint = adapter._build_query_endpoint(query, {}, perspective="published")
    response = adapter._make_request("GET", endpoint)
    response.raise_for_status()
    rows = response.json().get("result") or []
    hrefs_by_slug: Dict[str, List[str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        path = row.get("slugPath") or ""
        hrefs = [h for h in (row.get("hrefs") or []) if isinstance(h, str)]
        hrefs_by_slug[path] = hrefs
    return hrefs_by_slug


def fetch_rescue_links(
    topic: str,
    max_results: int = 3,
    exclude_slug: str = "",
) -> Dict[str, Any]:
    """Same related-post candidates as ``fetch_internal_links_tool``,
    ordered orphan-first: each candidate carries ``inbound`` (how many
    other posts link to it) and ``needs_rescue`` (<3 inbound)."""
    try:
        adapter = _build_adapter()
        candidates: List[Dict[str, str]] = adapter.fetch_internal_links(
            topic=topic,
            max_results=max(max_results * 2, max_results),
            exclude_slug=exclude_slug or None,
        )
        if not candidates:
            return {
                "status": "success",
                "links": [],
                "message": f"No internal link candidates for '{topic}'.",
            }
        hrefs_by_slug = _fetch_all_hrefs(adapter)
        slugs = [c.get("slug", "") for c in candidates]
        counts = inbound_counts(
            hrefs_by_slug, slugs, self_slug=exclude_slug or None
        )
        enriched = []
        for candidate in candidates:
            inbound = counts.get(candidate.get("slug", ""), 0)
            enriched.append(
                {
                    **candidate,
                    "inbound": inbound,
                    "needs_rescue": inbound < 3,
                }
            )
        ordered = rescue_order(enriched, counts)
        limited = ordered[: max(1, max_results)]
        rescue_n = sum(1 for c in limited if c["needs_rescue"])
        return {
            "status": "success",
            "links": limited,
            "message": (
                f"Ordered {len(limited)} internal link candidates for "
                f"'{topic}' ({rescue_n} need rescue: <3 inbound links)."
            ),
        }
    except Exception as exc:  # env missing / network — degrade like peers
        return {
            "status": "error",
            "links": [],
            "error": f"Failed to fetch rescue links: {exc}",
        }


check_link_hygiene_tool = function_tool(
    check_link_hygiene,
    name_override="check_link_hygiene_tool",
)
fetch_rescue_links_tool = function_tool(
    fetch_rescue_links,
    name_override="fetch_rescue_links_tool",
)
