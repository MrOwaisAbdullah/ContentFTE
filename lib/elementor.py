"""Elementor render target — native REST integration (spec §5.11/§5.13).

Elementor >= 3.27 registers its document meta with `show_in_rest`, so the
existing WordPress application-password connection (no MCP server, no
plugin of ours) can read and write layouts directly:

    _elementor_data           string whose value is a plain JSON ARRAY of
                              root elements — NOT the legacy
                              {"version": "0.4", "content": [...]} wrapper
                              (older exports only; accepted on read)
    _elementor_edit_mode      "builder"
    _elementor_template_type  "wp-post" | "wp-page"
    _elementor_page_settings  object, e.g. {"hide_title": "yes"}

Element shape (plain dict, 7-char hex ids like the editor generates):

    {"id": "a1b2c3d", "elType": "container"|"widget", "widgetType"?,
     "settings": {...}, "elements": [...], "isInner": bool}

Caveats this module carries:

- REST meta writes bypass Elementor's `Document::save()` invalidation of
  `_elementor_css` / `_elementor_element_cache` (Elementor 4.2), so the
  generated CSS can lag until the post is next saved inside Elementor —
  `save_document()` reports that as `cache_note`.
- Meta values are not kses-filtered (unlike post content), so HTML widgets
  may carry JSON-LD <script> tags — write with an Administrator app
  password (a lower role can still fail the meta update).
- Fail-open lives one layer up (`WordPressConnector.publish` + sdk
  service): this client raises on HTTP failure like `WordPressConnector`
  does; callers that must not fail catch.

No LLM calls — pure HTTP, never touches the model router.
"""
from __future__ import annotations

import html
import json
import uuid
from typing import TYPE_CHECKING, Any

import requests

if TYPE_CHECKING:  # runtime import would cycle (wordpress.publish imports us)
    from lib.wordpress import WPConfig

_CACHE_NOTE = (
    "Elementor CSS cache may lag: REST meta writes bypass Document::save() "
    "invalidation of _elementor_css (Elementor 4.2) — re-save the page in "
    "Elementor if styles look stale."
)


def _eid() -> str:
    """Elementor element ids are 7-char hex — mirror the editor."""
    return uuid.uuid4().hex[:7]


def build_blog_page_data(
    title: str,
    body_html: str,
    *,
    header_size: str = "h1",
    container_settings: dict | None = None,
    faqs: list | None = None,
) -> list[dict]:
    """Compose a blog document: heading widget + html widget (+ FAQ accordion).

    Pure — no I/O. The heading carries the H1 (callers that hide the
    WordPress title via page settings rely on it). `body_html` is the full
    rendered article body (plain HTML, may include JSON-LD).

    `faqs` ([{question, answer}, ...]) become a heading widget plus a native
    Elementor Accordion widget *after* the html widget — the FAQ never rides
    inside the html widget, so items collapse/expand with the real widget.
    """
    elements: list[dict] = [
        {
            "id": _eid(),
            "elType": "widget",
            "isInner": False,
            "widgetType": "heading",
            "settings": {"title": title, "header_size": header_size},
            "elements": [],
        },
        {
            "id": _eid(),
            "elType": "widget",
            "isInner": False,
            "widgetType": "html",
            "settings": {"html": body_html},
            "elements": [],
        },
    ]
    if faqs:
        accordion = _faq_accordion_widget(faqs)
        if accordion:
            elements.append({
                "id": _eid(),
                "elType": "widget",
                "isInner": False,
                "widgetType": "heading",
                "settings": {"title": "Frequently Asked Questions", "header_size": "h2"},
                "elements": [],
            })
            elements.append(accordion)
    return [
        {
            "id": _eid(),
            "elType": "container",
            "isInner": False,
            "settings": {"content_width": "full", **(container_settings or {})},
            "elements": elements,
        }
    ]


def _faq_accordion_widget(faqs: list) -> dict | None:
    """Native Elementor Accordion widget (widgetType=accordion).

    Schema verified against elementor/includes/widgets/accordion.php: the
    repeater control is `tabs` (label "Accordion Items") with `tab_title`
    (TEXT) and `tab_content` (WYSIWYG) fields; repeater items carry a 7-char
    hex `_id`. Control defaults (`selected_icon`, `title_html_tag`, …) are
    applied server-side by Elementor, so only the content is set here.
    """
    tabs = []
    for f in faqs or []:
        q = str(f.get("question") or "").strip()
        if not q:
            continue
        a = str(f.get("answer") or "").strip()
        body = a if a.lstrip().startswith("<") else f"<p>{html.escape(a)}</p>"
        tabs.append({"_id": _eid(), "tab_title": q, "tab_content": body})
    if not tabs:
        return None
    return {
        "id": _eid(),
        "elType": "widget",
        "isInner": False,
        "widgetType": "accordion",
        "settings": {"tabs": tabs},
        "elements": [],
    }


def elementor_meta(
    elements: list[dict],
    *,
    template_type: str = "wp-post",
    page_settings: dict | None = None,
) -> dict:
    """The `_elementor_*` meta dict for a REST write.

    `_elementor_data` is a STRING containing the JSON array (schema type:
    string). Page settings are only included when explicitly given — a
    partial meta update must not clobber settings the editor owns.
    """
    meta: dict[str, Any] = {
        "_elementor_data": json.dumps(elements, ensure_ascii=False),
        "_elementor_edit_mode": "builder",
        "_elementor_template_type": template_type,
    }
    if page_settings is not None:
        meta["_elementor_page_settings"] = page_settings
    return meta


class ElementorClient:
    """Read/write Elementor documents over WP REST using WPConfig auth.

    Same auth/connection model as `lib.wordpress.WordPressConnector`
    (constructor accepts any WPConfig-like object with base_url,
    auth_header(), timeout).
    """

    def __init__(self, config: "WPConfig"):
        if not getattr(config, "base_url", ""):
            raise ValueError("WP base_url required")
        self.cfg = config
        self.session = requests.Session()
        self.session.headers.update(config.auth_header())

    def _url(self, path: str) -> str:
        return f"{self.cfg.base_url}/wp-json/wp/v2{path}"

    @property
    def _timeout(self) -> float:
        return float(getattr(self.cfg, "timeout", 30.0) or 30.0)

    # --- probe ---

    def available(self) -> dict:
        """Is `_elementor_data` registered with show_in_rest? (OPTIONS probe)"""
        resp = self.session.options(self._url("/posts"), timeout=self._timeout)
        resp.raise_for_status()
        schema = resp.json().get("schema") or {}
        meta_schema = schema.get("meta") or {}
        props = meta_schema.get("properties") or {}
        keys = sorted(k for k in props if k.startswith("_elementor"))
        ok = "_elementor_data" in props
        return {
            "available": ok,
            "meta_keys": keys,
            "hint": "" if ok else
                    "Elementor >= 3.27 required (it must register document meta with show_in_rest)",
        }

    # --- read ---

    def get_document(self, post_id: int, post_type: str = "posts") -> dict:
        """Fetch the current Elementor document (elements + page settings)."""
        if post_type not in ("posts", "pages"):
            raise ValueError("post_type must be 'posts' or 'pages'")
        resp = self.session.get(
            self._url(f"/{post_type}/{post_id}"),
            params={"context": "edit", "_fields": "id,link,status,meta"},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        doc = resp.json()
        meta = doc.get("meta") or {}
        raw = meta.get("_elementor_data") or "[]"
        parse_error = ""
        elements: Any = raw
        if isinstance(raw, str):
            try:
                elements = json.loads(raw)
            except (TypeError, ValueError) as exc:
                parse_error = f"_elementor_data is not valid JSON: {exc}"
                elements = []
        if isinstance(elements, dict):  # legacy {"version","content"} wrapper
            elements = elements.get("content") or []
        if not isinstance(elements, list):
            parse_error = parse_error or "_elementor_data did not contain an array"
            elements = []
        return {
            "id": doc.get("id", post_id),
            "url": doc.get("link", ""),
            "status": doc.get("status", ""),
            "is_elementor": bool(elements) or meta.get("_elementor_edit_mode") == "builder",
            "edit_mode": meta.get("_elementor_edit_mode", ""),
            "template_type": meta.get("_elementor_template_type", ""),
            "page_settings": meta.get("_elementor_page_settings") or {},
            "elements": elements,
            "element_count": len(elements),
            **({"parse_error": parse_error} if parse_error else {}),
        }

    # --- write ---

    def save_document(
        self,
        post_id: int,
        elements: list[dict],
        *,
        post_type: str = "posts",
        page_settings: dict | None = None,
        template_type: str = "wp-post",
    ) -> dict:
        """Replace the document's root elements (full-document write)."""
        if post_type not in ("posts", "pages"):
            raise ValueError("post_type must be 'posts' or 'pages'")
        if not isinstance(elements, list) or not elements or not all(
            isinstance(e, dict) for e in elements
        ):
            raise ValueError(
                "elements must be a non-empty array of root element objects "
                '(e.g. [{"id","elType","settings","elements"}])'
            )
        payload = {"meta": elementor_meta(
            elements, template_type=template_type, page_settings=page_settings,
        )}
        resp = self.session.post(
            self._url(f"/{post_type}/{post_id}"), json=payload, timeout=self._timeout,
        )
        resp.raise_for_status()
        doc = resp.json()
        return {
            "ok": True,
            "id": doc.get("id", post_id),
            "url": doc.get("link", ""),
            "saved_elements": len(elements),
            "cache_note": _CACHE_NOTE,
        }
