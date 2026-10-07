"""§5.11 WordPress body rendering — Markdown → WP-safe HTML.

Pure functions, no HTTP, no LLM. Renders the pieces the connector needs:

- `markdown_to_wp_html`: headings, paragraphs, lists (nested), blockquotes,
  fenced code, GFM tables, hr, and inline marks (bold/italic/code/strike/
  `==highlight==`/links/images).
- **Block mode (default)**: every top-level element is wrapped in
  `<!-- wp:… -->` delimiters (Gutenberg serialization) so the post opens in
  the block editor as *real blocks* — no manual "Convert to Blocks" click and
  no risk of a user breaking content by converting. `blocks=False` returns
  plain HTML (used for the custom-site payload).
- **Shortcode-safe**: a literal `[` in body text is escaped to `&#91;` so
  WordPress never mistakes prose for a shortcode (links are parsed first, so
  real `[text](url)` links still work).
- `render_faq_block` / `render_cta_block`: the on-page FAQ + CTA blocks
  (wrapped in `<!-- wp:html -->` so they round-trip without validation).
- `inject_inpost_images`: place `<figure>` images right after a chosen H2
  (detects block mode and inserts after the heading block's closing comment).
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


def _block(name: str, inner: str, attrs: Optional[Dict[str, Any]] = None) -> str:
    """Gutenberg serialization: `<!-- wp:name {attrs} -->inner<!-- /wp:name -->`."""
    open_c = f"<!-- wp:{name}"
    if attrs:
        open_c += " " + json.dumps(attrs, separators=(",", ":"))
    open_c += " -->"
    return f"{open_c}\n{inner}\n<!-- /wp:{name} -->"


def markdown_to_wp_html(md: str, blocks: bool = True) -> str:
    """Markdown → WordPress HTML. Deterministic, dependency-free.

    `blocks=True` (default) wraps each top-level element in Gutenberg
    block delimiters so the post opens directly as editable blocks.
    """
    lines = (md or "").replace("\r\n", "\n").split("\n")
    out: List[str] = []
    i = 0
    n = len(lines)

    def emit(name: str, inner: str, attrs: Optional[Dict[str, Any]] = None) -> None:
        out.append(_block(name, inner, attrs) if blocks else inner)

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
            escaped = html.escape(chr(10).join(code))
            if blocks:
                # core/code save markup: no language class (attrs must round-trip)
                emit("code", f'<pre class="wp-block-code"><code>{escaped}</code></pre>')
            else:
                cls = f' class="language-{html.escape(lang)}"' if lang else ""
                emit("code", f"<pre><code{cls}>{escaped}</code></pre>")
            continue

        if not line.strip():
            i += 1
            continue

        if _HR_RE.match(line):
            # separator block save markup is uncertain across versions — wp:html
            # round-trips verbatim with zero validation risk.
            emit("html", "<hr>")
            i += 1
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            inner = f"<h{level}>{inline(heading.group(2).strip())}</h{level}>"
            emit("heading", inner, None if level == 2 else {"level": level})
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
            table = f"<table><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table>"
            if blocks:
                # core/table saves inside <figure class="wp-block-table">
                emit("table", f'<figure class="wp-block-table">{table}</figure>')
            else:
                emit("table", table)
            continue

        if line.lstrip().startswith("> "):
            quote: List[str] = []
            while i < n and lines[i].lstrip().startswith("> "):
                quote.append(lines[i].lstrip()[2:])
                i += 1
            content = inline(" ".join(quote))
            if blocks:
                # core/quote save: <blockquote class="wp-block-quote"><p>…</p></blockquote>
                emit("quote",
                     f'<blockquote class="wp-block-quote"><p>{content}</p></blockquote>')
            else:
                emit("quote", f"<blockquote>{content}</blockquote>")
            continue

        if _ULI_RE.match(line) or _OLI_RE.match(line):
            html_list, i = _render_list(lines, i)
            ordered = html_list.startswith("<ol>")
            emit("list", html_list, {"ordered": True} if blocks and ordered else None)
            continue

        # paragraph: consume until blank / block start
        para: List[str] = [line.strip()]
        i += 1
        while i < n and lines[i].strip() and not _starts_block(lines[i], lines, i):
            para.append(lines[i].strip())
            i += 1
        emit("paragraph", f"<p>{inline(' '.join(para))}</p>")

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
def render_faq_block(faqs: List[Dict[str, Any]], blocks: bool = True) -> str:
    parts = ['<section class="faq-block">', "<h2>Frequently Asked Questions</h2>"]
    for f in faqs or []:
        q = inline(str(f.get("question", "")))
        a = inline(str(f.get("answer", "")))
        parts.append(
            f'<div class="faq-item"><h3 class="faq-question">{q}</h3>'
            f'<p class="faq-answer">{a}</p></div>'
        )
    parts.append("</section>")
    body = "\n".join(parts)
    # custom classes survive verbatim inside wp:html (no block validation)
    return _block("html", body) if blocks else body


def render_cta_block(label: str, url: str, text: str = "",
                     is_client_owned: bool = True, blocks: bool = True) -> str:
    rel = "" if is_client_owned else ' rel="sponsored"'
    href = html.escape(url or "", quote=True)
    body = f"<p>{inline(text)}</p>" if text else ""
    out = (
        f'<aside class="cta-block">{body}'
        f'<a class="cta-button" href="{href}"{rel}>{html.escape(label or "", True)}</a>'
        f"</aside>"
    )
    return _block("html", out) if blocks else out


def _figure(src: str, alt: str, blocks: bool = False) -> str:
    if blocks:
        # core/image save markup: figure.wp-block-image + void <img ... />
        return (f'<figure class="wp-block-image"><img src="{html.escape(src, quote=True)}" '
                f'alt="{html.escape(alt or "", quote=True)}" /></figure>')
    return (f'<figure class="wp-block-image"><img src="{html.escape(src, quote=True)}" '
            f'alt="{html.escape(alt or "", quote=True)}"></figure>')


def inject_inpost_images(html_body: str, images: List[Dict[str, Any]]) -> str:
    """Insert each image after the `after_h2`-th `<h2>` (1-based).

    `images` items: {url|src, alt, after_h2?}. Missing/out-of-range after_h2
    appends at the end so an image is never silently dropped.

    Auto-detects block mode: when the body contains `<!-- wp:` delimiters the
    image is inserted after the heading block's closing comment (never inside
    it) and serialized as a core/image block.
    """
    blocks = "<!-- wp:" in html_body
    # block mode: anchor only on real heading blocks (`</h2><!-- /wp:heading -->`),
    # never on the FAQ <h2> that lives inside a wp:html block.
    anchor = re.compile(r"</h2>\s*<!-- /wp:heading -->") if blocks else re.compile(r"</h2>")
    body = html_body
    trailing: List[str] = []
    for img in images or []:
        figure = _figure(img.get("url") or img.get("src") or "", img.get("alt", ""), blocks)
        wrapped = _block("image", figure) if blocks else figure
        idx = img.get("after_h2")
        if not idx:
            trailing.append(wrapped)
            continue
        positions = [m.end() for m in anchor.finditer(body)]
        if 1 <= int(idx) <= len(positions):
            pos = positions[int(idx) - 1]
            body = body[:pos] + "\n" + wrapped + body[pos:]
        else:
            trailing.append(wrapped)
    if trailing:
        body = body + "\n" + "\n".join(trailing)
    return body


def jsonld_script(schema: Optional[dict]) -> str:
    if not schema:
        return ""
    return f'<script type="application/ld+json">{json.dumps(schema, ensure_ascii=False)}</script>'
