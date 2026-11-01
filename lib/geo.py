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


def person_node(author: dict | None) -> dict | None:
    """schema.org Person from a site's configured author. None when no name is configured —
    the engine never invents an author (a made-up byline is an E-E-A-T liability)."""
    if not isinstance(author, dict) or not str(author.get("name") or "").strip():
        return None
    node: dict = {"@type": "Person", "name": str(author["name"]).strip()}
    if str(author.get("url") or "").strip():
        node["url"] = str(author["url"]).strip()
    same_as = [str(u).strip() for u in (author.get("same_as") or author.get("sameAs") or []) if str(u).strip()]
    if same_as:
        node["sameAs"] = same_as
    if str(author.get("job_title") or "").strip():
        node["jobTitle"] = str(author["job_title"]).strip()
    return node


def organization_node(publisher: dict | None) -> dict | None:
    """schema.org Organization (with a logo ImageObject when one is configured)."""
    if not isinstance(publisher, dict) or not str(publisher.get("name") or "").strip():
        return None
    node: dict = {"@type": "Organization", "name": str(publisher["name"]).strip()}
    if str(publisher.get("url") or "").strip():
        node["url"] = str(publisher["url"]).strip()
    if str(publisher.get("logo_url") or "").strip():
        logo: dict = {"@type": "ImageObject", "url": str(publisher["logo_url"]).strip()}
        for src, dst in (("logo_width", "width"), ("logo_height", "height")):
            if publisher.get(src):
                logo[dst] = int(publisher[src])
        node["logo"] = logo
    return node


def image_node(image: "str | dict | None") -> "dict | None":
    """ImageObject from a URL or {url,width,height,caption}."""
    if not image:
        return None
    if isinstance(image, str):
        return {"@type": "ImageObject", "url": image}
    if not str(image.get("url") or "").strip():
        return None
    node: dict = {"@type": "ImageObject", "url": str(image["url"]).strip()}
    for k in ("width", "height"):
        if image.get(k):
            node[k] = int(image[k])
    if str(image.get("caption") or "").strip():
        node["caption"] = str(image["caption"]).strip()
    return node


def identity_from_settings(settings: dict | None, site_name: str = "", base_url: str = "") -> dict:
    """{'author': {...}|None, 'publisher': {...}|None} from `Site.settings["identity"]`.

        settings["identity"] = {
            "author":    {"name", "url", "same_as": [...], "job_title"},
            "publisher": {"name", "url", "logo_url", "logo_width", "logo_height"},
        }

    The publisher falls back to the site's own name/URL (real values); the author has NO
    fallback — without a configured author the markup simply omits it."""
    ident = (settings or {}).get("identity") if isinstance(settings, dict) else None
    ident = ident if isinstance(ident, dict) else {}
    publisher = dict(ident.get("publisher") or {})
    publisher.setdefault("name", site_name or "")
    publisher.setdefault("url", base_url or "")
    return {"author": ident.get("author") if isinstance(ident.get("author"), dict) else None,
            "publisher": publisher}


def article_schema(
    title: str,
    url: str,
    date_published: str | None = None,
    date_modified: str | None = None,
    entities: list[dict] | None = None,
    *,
    author: dict | None = None,
    publisher: dict | None = None,
    image: "str | dict | None" = None,
    description: str = "",
    keywords: list[str] | None = None,
    word_count: int | None = None,
    in_language: str = "",
    article_section: str = "",
) -> dict:
    """Article JSON-LD. The first five arguments keep their original meaning; everything
    after `*` is optional enrichment, and each field appears only when a real value exists
    (author/publisher come from site settings — see `identity_from_settings`)."""
    now = datetime.now(timezone.utc).isoformat()
    out: dict = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": title,
        "url": url,
        "datePublished": date_published or now,
        "dateModified": date_modified or date_published or now,
        "about": entities or [],
    }
    if url:
        out["mainEntityOfPage"] = {"@type": "WebPage", "@id": url}
    if (description or "").strip():
        out["description"] = description.strip()
    person, org, img = person_node(author), organization_node(publisher), image_node(image)
    if person:
        out["author"] = person
    if org:
        out["publisher"] = org
    if img:
        out["image"] = img
    kws = [k for k in (keywords or []) if str(k).strip()]
    if kws:
        out["keywords"] = ", ".join(kws)
    if word_count:
        out["wordCount"] = int(word_count)
    if in_language:
        out["inLanguage"] = in_language
    if article_section:
        out["articleSection"] = article_section
    return out


def build_article_graph(
    *,
    title: str,
    url: str,
    site_url: str,
    site_name: str = "",
    date_published: str | None = None,
    date_modified: str | None = None,
    description: str = "",
    author: dict | None = None,
    publisher: dict | None = None,
    image: "str | dict | None" = None,
    keywords: list[str] | None = None,
    word_count: int | None = None,
    in_language: str = "en",
    faqs: list[dict] | None = None,
    breadcrumb: list[tuple[str, str]] | None = None,
) -> dict:
    """The linked `@graph` form (Organization, Person, WebSite, WebPage, ImageObject,
    BlogPosting, BreadcrumbList, optional FAQPage), cross-referenced by `@id` so each entity is
    defined once. Nodes without real data are omitted rather than faked."""
    site = (site_url or "").rstrip("/")
    page = url
    ids = {"org": f"{site}/#organization", "person": f"{site}/#person", "site": f"{site}/#website",
           "page": f"{page}#webpage", "img": f"{page}#primaryimage", "post": f"{page}#article",
           "crumbs": f"{page}#breadcrumb", "faq": f"{page}#faq"}
    graph: list[dict] = []
    org = organization_node(publisher)
    if org:
        graph.append({**org, "@id": ids["org"]})
    person = person_node(author)
    if person:
        graph.append({**person, "@id": ids["person"]})
    graph.append({"@type": "WebSite", "@id": ids["site"], "url": site, "name": site_name or (org or {}).get("name", ""),
                  **({"publisher": {"@id": ids["org"]}} if org else {})})
    img = image_node(image)
    web: dict = {"@type": "WebPage", "@id": ids["page"], "url": page, "name": title,
                 "isPartOf": {"@id": ids["site"]}, "inLanguage": in_language}
    if img:
        web["primaryImageOfPage"] = {"@id": ids["img"]}
        graph.append({**img, "@id": ids["img"]})
    crumbs = breadcrumb or [("Home", site + "/"), ("Blog", site + "/blog"), (title, page)]
    web["breadcrumb"] = {"@id": ids["crumbs"]}
    graph.append(web)
    post: dict = {"@type": "BlogPosting", "@id": ids["post"], "mainEntityOfPage": {"@id": ids["page"]},
                  "headline": title[:110], "datePublished": date_published or datetime.now(timezone.utc).isoformat(),
                  "dateModified": date_modified or date_published or datetime.now(timezone.utc).isoformat(),
                  "inLanguage": in_language}
    if (description or "").strip():
        post["description"] = description.strip()
    if img:
        post["image"] = {"@id": ids["img"]}
    if person:
        post["author"] = {"@id": ids["person"]}
    if org:
        post["publisher"] = {"@id": ids["org"]}
    kws = [k for k in (keywords or []) if str(k).strip()]
    if kws:
        post["keywords"] = ", ".join(kws)
    if word_count:
        post["wordCount"] = int(word_count)
    graph.append(post)
    graph.append({"@type": "BreadcrumbList", "@id": ids["crumbs"],
                  "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": n, "item": u}
                                      for i, (n, u) in enumerate(crumbs)]})
    if faqs:
        graph.append({"@type": "FAQPage", "@id": ids["faq"], "mainEntity": faq_schema(faqs)["mainEntity"]})
    return {"@context": "https://schema.org", "@graph": graph}


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
