"""Plan SEC-06: rendered WordPress HTML must not carry executable URLs or let
JSON-LD break out of its <script> tag. Markdown comes from LLM drafts that ingest
untrusted web research, so these inputs are reachable by prompt injection."""
from __future__ import annotations

import json
import re

import pytest

from lib.wp_render import inline, jsonld_script, safe_url


@pytest.mark.parametrize("bad", [
    "javascript:alert(1)",
    "JaVaScRiPt:alert(1)",
    " javascript:alert(1)",
    "java\tscript:alert(1)",
    "java\nscript:alert(1)",
    "vbscript:msgbox(1)",
    "data:text/html;base64,PHNjcmlwdD4=",
    "file:///etc/passwd",
])
def test_unsafe_link_schemes_are_never_rendered_as_links(bad):
    out = inline(f"[click me]({bad})")
    assert "<a" not in out and "href" not in out
    assert "click me" in out          # the visible text survives
    assert safe_url(bad) == ""


@pytest.mark.parametrize("good", [
    "https://example.com/a?x=1&y=2",
    "http://example.com",
    "mailto:hi@example.com",
    "tel:+15551234567",
    "/relative/path",
    "#anchor",
    "../up",
    "page.html",
])
def test_safe_link_targets_still_render(good):
    out = inline(f"[label]({good})")
    assert out.startswith("<a href=") and "label</a>" in out
    assert safe_url(good) == good


def test_images_only_allow_http_and_relative_sources():
    assert "<img" not in inline("![x](data:image/svg+xml;base64,AAAA)")
    assert "<img" not in inline("![x](javascript:alert(1))")
    assert "<img" not in inline("![x](mailto:a@b.co)")      # not an image scheme
    assert 'src="https://a.test/i.png"' in inline("![x](https://a.test/i.png)")
    assert 'src="/i.png"' in inline("![x](/i.png)")


def test_attribute_breakout_is_still_escaped():
    out = inline('[x](https://a.test/"onmouseover="alert(1))')
    assert '"onmouseover="' not in out
    assert "&quot;" in out or "<a" not in out


def test_jsonld_cannot_close_its_script_tag():
    schema = {
        "headline": "</script><script>alert(1)</script>",
        "faq": "a < b && c > d",
        "sep": "line sep",
    }
    html_out = jsonld_script(schema)
    inner = re.fullmatch(r'<script type="application/ld\+json">(.*)</script>', html_out, re.S)
    assert inner, html_out
    body = inner.group(1)
    assert "</script" not in body.lower()
    assert "<" not in body and ">" not in body
    assert json.loads(body) == schema      # identical data for crawlers


def test_empty_schema_renders_nothing():
    assert jsonld_script(None) == "" and jsonld_script({}) == ""
