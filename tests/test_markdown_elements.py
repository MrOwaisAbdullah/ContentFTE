"""End-to-end markdown element fidelity: generator markdown -> Sanity
Portable Text (markdown_parser) and back (adapter reverse converter).

Covers: headings, paragraphs, bullets (+nested level), ordered lists,
blockquotes, inline code, code blocks, images (standalone + inline),
highlight, strikethrough, underline, links, tables, thematic breaks.
"""
import pytest

from lib.markdown_parser import markdown_to_sanity_blocks


def _blocks(md):
    return markdown_to_sanity_blocks(md)


def _spans(block):
    return block.get("children", [])


def _text(block):
    return "".join(c.get("text", "") for c in _spans(block))


def _marks_of(block):
    return {m for c in _spans(block) for m in (c.get("marks") or [])}


# ---------------------------------------------------------------- headings

def test_headings_h1_to_h6_and_paragraph():
    md = "# H1\n\npara\n\n## H2\n\n### H3\n\n#### H4\n\n##### H5\n\n###### H6"
    styles = [b.get("style") for b in _blocks(md) if b.get("_type") == "block"]
    assert styles == ["h1", "normal", "h2", "h3", "h4", "h5", "h6"]


def test_paragraph_keeps_inline_marks():
    md = "Some **bold** and *italic* and `code` text."
    block = _blocks(md)[0]
    assert block["style"] == "normal"
    assert {"strong", "em", "code"} <= _marks_of(block)
    assert "bold" in _text(block)


# ------------------------------------------------------------------- lists

def test_bullet_list_and_nested_level():
    md = "- one\n- two\n  - nested\n- three"
    items = [b for b in _blocks(md) if b.get("listItem")]
    assert [b.get("listItem") for b in items] == ["bullet"] * 4
    assert [_text(b) for b in items] == ["one", "two", "nested", "three"]
    assert [b.get("level", 1) for b in items] == [1, 1, 2, 1]


def test_ordered_list_maps_to_number_listitem():
    md = "1. first\n2. second"
    items = [b for b in _blocks(md) if b.get("listItem")]
    assert [b.get("listItem") for b in items] == ["number", "number"]
    assert [_text(b) for b in items] == ["first", "second"]


def test_uniform_deep_indent_is_dedented_not_code():
    # every line indented 4+ spaces: uniform dedent, relative nesting kept
    md = "    - one\n      - nested\n    - two"
    items = [b for b in _blocks(md) if b.get("listItem")]
    assert len(items) == 3
    assert not any(b.get("_type") == "code" for b in _blocks(md))


# --------------------------------------------------------------- blockquote

def test_blockquote_style():
    md = "> **TL;DR** - the answer in one line."
    block = _blocks(md)[0]
    assert block["style"] == "blockquote"
    assert "strong" in _marks_of(block)


# -------------------------------------------------------------------- code

def test_fenced_code_becomes_code_object_with_language():
    md = "```python\ndef f(x):\n    return x + 1\n```"
    blocks = _blocks(md)
    assert len(blocks) == 1
    code = blocks[0]
    assert code["_type"] == "code"
    assert code["language"] == "python"
    assert code["code"] == "def f(x):\n    return x + 1"


def test_code_fence_stays_literal_through_preprocessing():
    md = "```text\nkeep ==raw== and ~~raw~~ here\n```"
    code = _blocks(md)[0]
    assert code["_type"] == "code"
    assert "==raw==" in code["code"] and "~~raw~~" in code["code"]


# ------------------------------------------------------------------ images

def test_standalone_image_becomes_image_block_with_url_asset():
    md = "intro\n\n![Alt text](https://example.com/pic.png \"cap\")"
    images = [b for b in _blocks(md) if b.get("_type") == "image"]
    assert len(images) == 1
    assert images[0]["asset"]["url"] == "https://example.com/pic.png"
    assert images[0]["alt"] == "Alt text"


def test_inline_image_becomes_block_not_raw_markdown():
    md = "Text before ![inl](https://example.com/i.jpg) after."
    blocks = _blocks(md)
    kinds = [b.get("_type") for b in blocks]
    assert "image" in kinds
    # the paragraph must NOT contain raw markdown image syntax
    all_text = " ".join(
        c.get("text", "")
        for b in blocks if b.get("_type") == "block"
        for c in _spans(b)
    )
    assert "![" not in all_text
    assert "https://example.com/i.jpg" not in all_text


# ------------------------------------------------------------------- marks

def test_highlight_from_double_equals_and_mark_tags():
    md_a = "The ==key stat== here."
    md_b = "The <mark>key stat</mark> here."
    for md in (md_a, md_b):
        block = _blocks(md)[0]
        hl = [c["text"] for c in _spans(block) if "highlight" in (c.get("marks") or [])]
        assert hl == ["key stat"]
        assert "<mark>" not in _text(block)


def test_strikethrough_and_underline():
    md = "Drop ~~old advice~~ and <u>keep this</u>."
    block = _blocks(md)[0]
    strike = [c["text"] for c in _spans(block) if "strike-through" in (c.get("marks") or [])]
    under = [c["text"] for c in _spans(block) if "underline" in (c.get("marks") or [])]
    assert strike == ["old advice"]
    assert under == ["keep this"]
    assert "<u>" not in _text(block) and "~~" not in _text(block)


def test_link_becomes_markdef():
    md = "See [the guide](https://example.com/g)."
    block = _blocks(md)[0]
    defs = block.get("markDefs") or []
    assert defs and defs[0]["_type"] == "link"
    assert defs[0]["href"] == "https://example.com/g"
    link_keys = [m for m in _marks_of(block) if m.startswith("mark-def")]
    assert link_keys


# ------------------------------------------------------------------ tables

def test_gfm_table_becomes_table_object():
    md = (
        "| Feature | Plan A | Plan B |\n"
        "|---------|--------|--------|\n"
        "| Price   | **$10** | $20 |\n"
        "| Support | Email  | `24/7` |\n"
    )
    blocks = _blocks(md)
    tables = [b for b in blocks if b.get("_type") == "table"]
    assert len(tables) == 1
    rows = tables[0]["rows"]
    assert len(rows) == 3 and all(r["_type"] == "tableRow" for r in rows)
    header_cells = rows[0]["cells"]
    assert len(header_cells) == 3
    # cell children are block-shaped (array-of-block) holding spans
    first_data = rows[1]["cells"]
    bold_spans = [
        s for c in first_data
        for blk in c["children"]
        for s in blk.get("children", [])
        if "strong" in (s.get("marks") or [])
    ]
    assert bold_spans and bold_spans[0]["text"] == "$10"
    # no literal pipe table leaked into paragraph blocks
    joined = " ".join(
        c.get("text", "")
        for b in blocks if b.get("_type") == "block"
        for c in _spans(b)
    )
    assert "| Feature" not in joined


def test_table_needs_header_separator_not_any_pipe_line():
    md = "just a pipe | in prose\n\nnormal para"
    blocks = _blocks(md)
    assert not any(b.get("_type") == "table" for b in blocks)


# ------------------------------------------------------------ thematic break

def test_thematic_break_survives_as_content():
    md = "before\n\n---\n\nafter"
    texts = [
        "".join(c.get("text", "") for c in _spans(b))
        for b in _blocks(md) if b.get("_type") == "block"
    ]
    assert any("---" in t for t in texts)


# ------------------------------------------------- reverse (PT -> markdown)

def _reverse(blocks):
    from lib.sanity_adapter import SanityAdapter
    adapter = SanityAdapter(project_id="x", dataset="y", token="z")
    return adapter._portable_text_to_markdown(blocks)


def test_reverse_renders_new_marks():
    blocks = [{
        "_type": "block", "style": "normal", "markDefs": [],
        "children": [
            {"_type": "span", "text": "keep ", "marks": []},
            {"_type": "span", "text": "highlighted", "marks": ["highlight"]},
            {"_type": "span", "text": "old", "marks": ["strike-through"]},
            {"_type": "span", "text": "under", "marks": ["underline"]},
        ],
    }]
    md = _reverse(blocks)
    assert "==highlighted==" in md
    assert "~~old~~" in md
    assert "<u>under</u>" in md


def test_reverse_renders_code_object_and_table():
    blocks = [
        {"_type": "code", "language": "js", "code": "console.log(1)"},
        {
            "_type": "table",
            "rows": [
                {"_type": "tableRow", "cells": [
                    {"_type": "tableCell", "children": [
                        {"_type": "block", "style": "normal", "markDefs": [],
                         "children": [{"_type": "span", "text": "Col A"}]}]},
                    {"_type": "tableCell", "children": [
                        {"_type": "block", "style": "normal", "markDefs": [],
                         "children": [{"_type": "span", "text": "Col B"}]}]},
                ]},
                {"_type": "tableRow", "cells": [
                    {"_type": "tableCell", "children": [
                        {"_type": "block", "style": "normal", "markDefs": [],
                         "children": [{"_type": "span", "text": "1"}]}]},
                    {"_type": "tableCell", "children": [
                        {"_type": "block", "style": "normal", "markDefs": [],
                         "children": [{"_type": "span", "text": "2"}]}]},
                ]},
            ],
        },
    ]
    md = _reverse(blocks)
    assert "```js" in md and "console.log(1)" in md
    assert "| Col A | Col B |" in md
    assert "| --- | --- |" in md
    assert "| 1 | 2 |" in md


def test_reverse_renders_unuploaded_image_url():
    blocks = [{"_type": "image",
               "asset": {"url": "https://example.com/u.png"},
               "alt": "alt"}]
    md = _reverse(blocks)
    assert "![alt](https://example.com/u.png)" in md


def test_roundtrip_code_block_survives():
    md_in = "```python\nx = 1\ny = 2\n```"
    blocks = _blocks(md_in)
    md_out = _reverse(blocks)
    assert "```python" in md_out
    assert "x = 1" in md_out and "y = 2" in md_out


# --------------------------------------------------- generator instructions

def test_generator_allows_tables_and_rich_elements():
    from blog_agent.blog_agents import content_generator_agent
    instr = content_generator_agent.instructions
    assert "never raw pipe-table" not in instr
    assert "Do NOT use pipe-table Markdown syntax" not in instr
    assert "pipe table" in instr.lower()
    assert "==double equals==" in instr
    assert "fenced block" in instr
