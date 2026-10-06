"""§5.11 WordPress body rendering — Markdown → WP-safe HTML.

Pure functions, no HTTP, no LLM. Renders the pieces the connector needs:

- `markdown_to_wp_html`: headings, paragraphs, lists (nested), blockquotes,
  fenced code, GFM tables, hr, and inline marks (bold/italic/code/strike/
  `==highlight==`/links/images).
- **Shortcode-safe**: a literal `[` in body text is escaped to `&#91;` so
  WordPress never mistakes prose for a shortcode (links are parsed first, so
  real `[text](url)` links still work).
- `render_faq_block` / `render_cta_block`: the on-page FAQ + CTA blocks.
- `inject_inpost_images`: place `<figure>` images right after a chosen H2.
- `jsonld_script`: `<script type="application/ld+json">` for Article/FAQPage.
"""
from __future__ import annotations

import html
import json
import re
from typing import Any, Dict, List, Optional

# --- inline ---
_IMG_RE = re.compile(r'!\[(?P<alt>[^\]]*)\]\((?P<src>\S+?)(?:\s+"(?P<title>[^"]*)")?\)')
_LINK_RE = re.compile(r'(?<!\!)\[(?P<text>[^\]]+)\]\((?P<href>\S+?)(?:\s+"(?P<title>[^"]*)")?\)')
_CODE_RE = re.compile(r'`([^`]+)`')
_BOLD_ITALIC_RE = re.compile(r'\*\*\*(\S.*?\S|\S)\*\*\*')
_BOLD_RE = re.compile(r'\*\*(\S.*?\S|\S)\*\*')
_ITALIC_RE = re.compile(r'(?<![*\w])\*(\S.*?\S|\S)\*(?![*\w])')
_STRIKE_RE = re.compile(r'~~(\S.*?\S|\S)~~')
_HIGHLIGHT_RE = re.compile(r'==(\S.*?\S|\S)==')
_UNDERSCORE_EM_RE = re.compile(r'(?<![\w_])_(\S.*?\S|\S)_(?![\w_])')


def _escape_brackets(text: str) -> str:
    """Escape stray shortcode brackets (real links are protected beforehand)."""
    return text.replace("[", "&#91;").replace("]", "&#93;")


def inline(text: str) -> str:
    """Render one line/paragraph of inline Markdown to HTML (sanitized)."""
    if text is None:
        return ""
    protected: List[str] = []

    def _protect(match_html: str) -> str:
        protected.append(match_html)
        return f"\x00{len(protected) - 1}\x00"

    def _img(m: re.Match) -> str:
        alt = html.escape(m.group("alt") or "", quote=True)
        src = html.escape(m.group("src") or "", quote=True)
        title = m.group("title")
        t = f' title="{html.escape(title, quote=True)}"' if title else ""
        return _protect(f'<img src="{src}" alt="{alt}"{t}>')

    def _link(m: re.Match) -> str:
        href = html.escape(m.group("href") or "", quote=True)
        label = html.escape(m.group("text") or "", quote=True)
        title = m.group("title")
        t = f' title="{html.escape(title, quote=True)}"' if title else ""
        rel = ''
        return _protect(f'<a href="{href}"{t}{rel}>{label}</a>')

    text = _IMG_RE.sub(_img, text)
    text = _LINK_RE.sub(_link, text)

    text = html.escape(text, quote=False)  # sanitize the remaining prose
    text = _escape_brackets(text)
    text = _CODE_RE.sub(lambda m: f"<code>{m.group(1)}</code>", text)
    text = _BOLD_ITALIC_RE.sub(lambda m: f"<strong><em>{m.group(1)}</em></strong>", text)
    text = _BOLD_RE.sub(lambda m: f"<strong>{m.group(1)}</strong>", text)
    text = _STRIKE_RE.sub(lambda m: f"<del>{m.group(1)}</del>", text)
    text = _HIGHLIGHT_RE.sub(lambda m: f"<mark>{m.group(1)}</mark>", text)
    text = _ITALIC_RE.sub(lambda m: f"<em>{m.group(1)}</em>", text)
    text = _UNDERSCORE_EM_RE.sub(lambda m: f"<em>{m.group(1)}</em>", text)

    for i, chunk in enumerate(protected):
        text = text.replace(f"\x00{i}\x00", chunk)
    return text


# --- block ---
_FENCE_RE = re.compile(r"^\s*```\s*([\w+-]*)\s*$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_ULI_RE = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_OLI_RE = re.compile(r"^(\s*)\d+\.\s+(.*)$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")
_HR_RE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")


def _split_row(line: str) -> List[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def markdown_to_wp_html(md: str) -> str:
    """Markdown → WordPress-safe HTML. Deterministic, dependency-free."""
    lines = (md or "").replace("\r\n", "\n").split("\n")
    out: List[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]

        fence = _FENCE_RE.match(line)
        if fence:
            lang = fence.group(1)
            i += 1
            code: List[str] = []
            while i < n and not _FENCE_RE.match(lines[i]):
                code.append(lines[i])
                i += 1
            i += 1  # closing fence
            cls = f' class="language-{html.escape(lang)}"' if lang else ""
            out.append(f"<pre><code{cls}>{html.escape(chr(10).join(code))}</code></pre>")
            continue

        if not line.strip():
            i += 1
            continue

        if _HR_RE.match(line):
            out.append("<hr>")
            i += 1
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            out.append(f"<h{level}>{inline(heading.group(2).strip())}</h{level}>")
            i += 1
            continue

        # GFM table: header row + separator row
        if "|" in line and i + 1 < n and _TABLE_SEP_RE.match(lines[i + 1]):
            header = _split_row(line)
            i += 2
            body_rows: List[List[str]] = []
            while i < n and "|" in lines[i] and lines[i].strip():
                body_rows.append(_split_row(lines[i]))
                i += 1
            thead = "".join(f"<th>{inline(c)}</th>" for c in header)
            tbody = "".join(
                "<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>"
                for row in body_rows
            )
            out.append(f"<table><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table>")
            continue

        if line.lstrip().startswith("> "):
            quote: List[str] = []
            while i < n and lines[i].lstrip().startswith("> "):
                quote.append(lines[i].lstrip()[2:])
                i += 1
            out.append(f"<blockquote>{inline(' '.join(quote))}</blockquote>")
            continue

        if _ULI_RE.match(line) or _OLI_RE.match(line):
            html_list, i = _render_list(lines, i)
            out.append(html_list)
            continue

        # paragraph: consume until blank / block start
        para: List[str] = [line.strip()]
        i += 1
        while i < n and lines[i].strip() and not _starts_block(lines[i], lines, i):
            para.append(lines[i].strip())
            i += 1
        out.append(f"<p>{inline(' '.join(para))}</p>")

    return "\n".join(out)


def _starts_block(line: str, lines: List[str], i: int) -> bool:
    if _FENCE_RE.match(line) or _HEADING_RE.match(line) or _HR_RE.match(line):
        return True
    if line.lstrip().startswith("> ") or _ULI_RE.match(line) or _OLI_RE.match(line):
        return True
    if "|" in line and i + 1 < len(lines) and _TABLE_SEP_RE.match(lines[i + 1]):
        return True
    return False


def _render_list(lines: List[str], i: int) -> tuple[str, int]:
    """Render a (possibly nested) list; returns (html, next_index)."""
    ordered = bool(_OLI_RE.match(lines[i]))
    tag = "ol" if ordered else "ul"
    pattern = _OLI_RE if ordered else _ULI_RE
    items: List[str] = []
    n = len(lines)
    while i < n:
        m = pattern.match(lines[i])
        if not m:
            break
        indent = len(m.group(1))
        content = m.group(2)
        i += 1
        # nested list directly under this item
        nested = ""
        while i < n and lines[i].strip() and len(lines[i]) - len(lines[i].lstrip()) > indent \
                and (_ULI_RE.match(lines[i]) or _OLI_RE.match(lines[i])):
            nested, i = _render_list(lines, i)
        items.append(f"<li>{inline(content)}{nested}</li>")
    return f"<{tag}>" + "".join(items) + f"</{tag}>", i


# --- composed blocks ---
def render_faq_block(faqs: List[Dict[str, Any]]) -> str:
    parts = ['<section class="faq-block">', "<h2>Frequently Asked Questions</h2>"]
    for f in faqs or []:
        q = inline(str(f.get("question", "")))
        a = inline(str(f.get("answer", "")))
        parts.append(
            f'<div class="faq-item"><h3 class="faq-question">{q}</h3>'
            f'<p class="faq-answer">{a}</p></div>'
        )
    parts.append("</section>")
    return "\n".join(parts)


def render_cta_block(label: str, url: str, text: str = "", is_client_owned: bool = True) -> str:
    rel = "" if is_client_owned else ' rel="sponsored"'
    href = html.escape(url or "", quote=True)
    body = f"<p>{inline(text)}</p>" if text else ""
    return (
        f'<aside class="cta-block">{body}'
        f'<a class="cta-button" href="{href}"{rel}>{html.escape(label or "", quote=True)}</a>'
        f"</aside>"
    )


def _figure(src: str, alt: str) -> str:
    return (f'<figure class="wp-block-image"><img src="{html.escape(src, quote=True)}" '
            f'alt="{html.escape(alt or "", quote=True)}"></figure>')


def inject_inpost_images(html_body: str, images: List[Dict[str, Any]]) -> str:
    """Insert each image after the `after_h2`-th `<h2>` (1-based).

    `images` items: {url|src, alt, after_h2?}. Missing/out-of-range after_h2
    appends at the end so an image is never silently dropped.
    """
    body = html_body
    trailing: List[str] = []
    for img in images or []:
        figure = _figure(img.get("url") or img.get("src") or "", img.get("alt", ""))
        idx = img.get("after_h2")
        if not idx:
            trailing.append(figure)
            continue
        # find the nth </h2>
        positions = [m.end() for m in re.finditer(r"</h2>", body)]
        if 1 <= int(idx) <= len(positions):
            pos = positions[int(idx) - 1]
            body = body[:pos] + "\n" + figure + body[pos:]
        else:
            trailing.append(figure)
    if trailing:
        body = body + "\n" + "\n".join(trailing)
    return body


def jsonld_script(schema: Optional[dict]) -> str:
    if not schema:
        return ""
    return f'<script type="application/ld+json">{json.dumps(schema, ensure_ascii=False)}</script>'
