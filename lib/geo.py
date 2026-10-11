"""§5.6/5.7/5.8 AEO + GEO + SEO-core helpers (pure functions, no LLM).

Covers: TL;DR answer block, FAQ/Article JSON-LD, entity sameAs schema,
llms.txt generator, Markdown alternate emitter, IndexNow payload.
"""
from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone


def build_tldr(answer: str, word_min: int = 40, word_max: int = 60) -> str:
    words = (answer or "").split()
    if len(words) < word_min:
        raise ValueError(f"TL;DR too short: {len(words)} words, need {word_min}-{word_max}")
    if len(words) > word_max + 20:
        words = words[:word_max]
    return " ".join(words)


def tldr_block(answer: str) -> str:
    """Rendered directly after the H1 (§5.7)."""
    return f"> **TL;DR** — {build_tldr(answer)}"


# Matches the engine's `tldr_block` output (`> **TL;DR** — …`) and the
# looser variants a model emits (`> **TL;DR:** …`, `> TL;DR - …`). The dash
# is listed FIRST in the class so it stays a literal -- `[:-–—]` would be a
# range from ":" to "–" and quietly match the whole line. Only the preamble
# is searched -- see extract_tldr.
_TLDR_RE = re.compile(
    r"^\s*>\s*(?:\*\*)?\s*TL\s*;?\s*DR(?:\*\*)?\s*[-:–—]+\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)


def extract_tldr(markdown: str) -> str:
    """Pull the TL;DR sentence out of rendered markdown (inverse of
    `tldr_block`). Returns "" when the post carries no TL;DR block.

    Only the document preamble counts: the engine always emits the TL;DR as
    the opening blockquote, before the first H2. A `> TL;DR:` line that
    appears after a heading is body prose, not the TL;DR field.

    Needed because the TL;DR is currently only inline content: answer
    engines and site meta tags have to parse a blockquote out of Portable
    Text/blocks to see it. Callers use this to store it as a first-class
    field (Sanity `tldr`, delivery payload `seo.tldr`) instead."""
    if not markdown:
        return ""
    # Stop at the first H2 -- everything after it is body content.
    first_h2 = re.search(r"^##\s", markdown, flags=re.M)
    preamble = markdown[:first_h2.start()] if first_h2 else markdown
    match = _TLDR_RE.search(preamble[:800])
    if not match:
        return ""
    # strip a trailing `**` from the `> **TL;DR:** …**` variant
    text = match.group(1).strip().strip("*").strip()
    return re.sub(r"\s+", " ", text)


def slugify_taxonomy(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return slug or "uncategorized"


def next_available_slug(base: str, taken: set[str]) -> str:
    """Slug collision handling: append -2, -3… (§5.6). Unicode-safe."""
    base = slugify_taxonomy(base)
    if base not in taken:
        return base
    i = 2
    while f"{base}-{i}" in taken:
        i += 1
    return f"{base}-{i}"


def faq_schema(faqs: list[dict]) -> dict:
    entities = [
        {
            "@type": "Question",
            "name": f.get("question", ""),
            "acceptedAnswer": {"@type": "Answer", "text": f.get("answer", "")},
        }
        for f in faqs
    ]
    return {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": entities}


def article_schema(
    title: str,
    url: str,
    date_published: str | None = None,
    date_modified: str | None = None,
    entities: list[dict] | None = None,
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": title,
        "url": url,
        "datePublished": date_published or now,
        "dateModified": date_modified or now,
        "about": entities or [],
    }


def entity_with_sameas(name: str, same_as: list[str]) -> dict:
    """§5.8 entity grounding — every article declares entities + sameAs."""
    return {"@type": "Thing", "name": name, "sameAs": same_as}


def markdown_alternate(title: str, markdown_body: str, meta: dict | None = None) -> str:
    """Agent-ready `.md` alternate at a predictable URL (§5.8)."""
    front = json.dumps({"title": title, **(meta or {})}, indent=2)
    return f"---\n{front}\n---\n\n# {title}\n\n{markdown_body.strip()}\n"


def generate_llms_txt(site_name: str, site_url: str, key_pages: list[dict], policies: str = "") -> str:
    lines = [f"# {site_name}", "", f"> {site_url}", ""]
    lines.append("## Key pages")
    for page in key_pages:
        lines.append(f"- [{page.get('title', '')}]({page.get('url', '')})")
    if policies:
        lines += ["", "## Content policies", "", policies]
    return "\n".join(lines) + "\n"


def indexnow_payload(host: str, key: str, urls: list[str]) -> dict:
    return {"host": host, "key": key, "keyLocation": f"https://{host}/{key}.txt", "urlList": urls}


def sitemap_xml(entries: list[dict]) -> str:
    """§5.6 XML sitemap (sitemaps.org protocol 0.9, UTF-8).

    ``entries``: ``{"loc": <absolute url>, "lastmod": <W3C datetime>}``.
    ``<loc>`` is required per URL; ``<lastmod>`` optional. Escape is on
    both (query-string locs can contain ``&``).
    """
    from xml.sax.saxutils import escape

    rows = []
    for e in entries or []:
        loc = str((e or {}).get("loc") or "").strip()
        if not loc:
            continue
        row = f"  <url><loc>{escape(loc)}</loc>"
        lastmod = str((e or {}).get("lastmod") or "").strip()
        if lastmod:
            row += f"<lastmod>{escape(lastmod)}</lastmod>"
        rows.append(row + "</url>")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + ("\n".join(rows) + "\n" if rows else "")
        + "</urlset>\n"
    )


def sources_box(sources: list[dict]) -> str:
    """§5.4 visible trust signal — every article ends with this."""
    lines = ["## Sources"]
    for s in sources:
        title = html.escape(s.get("title", "Source"))
        publisher = html.escape(s.get("publisher", ""))
        url = s.get("url", "")
        suffix = f" ({publisher})" if publisher else ""
        lines.append(f"- [{title}]({url}){suffix}")
    return "\n".join(lines)


def sponsored_attrs(is_client_owned: bool) -> str:
    return "" if is_client_owned else ' rel="sponsored"'
