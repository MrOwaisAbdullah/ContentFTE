"""§5.11 WordPress connector — REST first (Application Passwords).

No plugin review, fully manageable, ships now. The connector already
does everything the later wordpress.org plugin would do, so the plugin
is a packaging step, not a rewrite.

Covers: HTML body, featured + in-post images, internal-link fetch via
REST, Yoast/RankMath/AIOSEO meta, taxonomy on demand, dup/slug guards,
outbound 200-check, draft vs auto modes, dateModified refresh.

Render targets (spec §5.11): `WP_RENDER_TARGET=blocks` (default) serializes
Gutenberg block markup; `elementor` keeps the post body as plain HTML and,
after the post exists, writes an Elementor document via REST meta
(`lib.elementor.ElementorClient`, Elementor >= 3.27) — fail-open: an
Elementor write failure never re-creates the post.

MCP interop (spec §5.13): interactive page-builder/plugin settings work
still belongs to MCP editors; the automated Elementor layout write is
native here (no MCP dependency). This connector owns the *publish* path
(create/update a post + media + terms + meta).

No LLM calls — pure HTTP. Never touches the model router.
"""
from __future__ import annotations

import base64
import mimetypes
import os
from dataclasses import dataclass, field

import requests

from lib import wp_render
from lib.geo import article_schema, faq_schema as build_faq_schema, next_available_slug
from lib.link_validator import validate_links


@dataclass
class WPConfig:
    base_url: str  # e.g. https://example.com
    username: str
    app_password: str
    timeout: float = 30.0

    @classmethod
    def from_env(cls, prefix: str = "WP_") -> "WPConfig":
        return cls(
            base_url=(os.environ.get(f"{prefix}BASE_URL") or "").rstrip("/"),
            username=os.environ.get(f"{prefix}USERNAME", ""),
            app_password=os.environ.get(f"{prefix}APP_PASSWORD", ""),
        )

    def auth_header(self) -> dict:
        token = base64.b64encode(f"{self.username}:{self.app_password}".encode()).decode()
        return {"Authorization": f"Basic {token}"}


@dataclass
class PreparedPost:
    title: str
    html: str
    markdown: str = ""
    excerpt: str = ""
    slug: str = ""
    categories: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    meta_title: str = ""
    meta_description: str = ""
    focus_keyphrase: str = ""
    canonical: str = ""
    featured_image_path: str | None = None
    featured_alt: str = ""
    inpost_images: list[dict] = field(default_factory=list)  # {path, alt, after_h2}
    faq_schema: dict | None = None
    article_schema: dict | None = None
    status: str = "draft"  # draft|publish
    render_target: str = "blocks"  # blocks|elementor (see _resolve_render_target)
    faqs: list[dict] = field(default_factory=list)  # raw pairs — Elementor accordion widget


def _resolve_render_target(override: str | None = None) -> str:
    """blocks (Gutenberg default) | elementor (plain HTML + REST doc write).

    `override` (build_prepared_post arg) beats WP_RENDER_TARGET; unknown
    values fall back to blocks so a typo never yields an unrenderable body.
    """
    raw = (override or os.environ.get("WP_RENDER_TARGET") or "blocks").strip().lower()
    return raw if raw in ("blocks", "elementor") else "blocks"


def build_prepared_post(
    *,
    title: str,
    markdown: str,
    url: str = "",
    faqs: list | None = None,
    categories: list | None = None,
    tags: list | None = None,
    meta_title: str = "",
    meta_description: str = "",
    focus_keyphrase: str = "",
    canonical: str = "",
    slug: str = "",
    excerpt: str = "",
    featured_image_path: str | None = None,
    featured_alt: str = "",
    inpost_images: list | None = None,
    cta: dict | None = None,
    entities: list | None = None,
    date_published: str | None = None,
    date_modified: str | None = None,
    status: str = "draft",
    render_target: str | None = None,
) -> PreparedPost:
    """Compose a PreparedPost: markdown → WP HTML (+ CTA + FAQ) + meta + schema.

    In-post images are injected at publish time (after they are uploaded, so
    the HTML carries the real media URLs), but their placement spec is carried
    on the post. No network here — pure composition.

    `render_target` (blocks|elementor, default from WP_RENDER_TARGET): in
    elementor mode the body is plain HTML (no Gutenberg block comments) so
    it can live inside an Elementor html widget; FAQ/CTA render unwrapped.
    """
    blocks = _resolve_render_target(render_target) == "blocks"
    body = wp_render.markdown_to_wp_html(markdown, blocks=blocks)
    if cta:
        body += "\n" + wp_render.render_cta_block(
            cta.get("label", ""), cta.get("url", ""), cta.get("text", ""),
            is_client_owned=cta.get("is_client_owned", True),
            blocks=blocks,
        )
    if faqs and blocks:
        # block mode: FAQ accordion as core/details blocks inside the body.
        # elementor mode leaves the body FAQ-free — publish() feeds post.faqs
        # to build_blog_page_data, which emits a native accordion widget.
        body += "\n" + wp_render.render_faq_block(faqs, blocks=True)
    # Yoast truncates displayed meta descriptions at ~156 chars — cut at a
    # word boundary so the snippet never ends mid-word or overflows.
    meta_description = (meta_description or "").strip()
    if len(meta_description) > 155:
        cut = meta_description[:155].rsplit(" ", 1)[0].rstrip(" ,;.-")
        meta_description = cut or meta_description[:155]
    return PreparedPost(
        title=title,
        html=body,
        markdown=markdown,
        excerpt=excerpt or meta_description,
        slug=slug or title,
        categories=list(categories or []),
        tags=list(tags or []),
        meta_title=meta_title or title,
        meta_description=meta_description,
        focus_keyphrase=(focus_keyphrase or "").strip(),
        canonical=canonical,
        featured_image_path=featured_image_path,
        featured_alt=featured_alt,
        inpost_images=list(inpost_images or []),
        faq_schema=build_faq_schema(faqs) if faqs else None,
        article_schema=article_schema(title, url or canonical, date_published, date_modified, entities),
        status=status,
        render_target=_resolve_render_target(render_target),
        faqs=[dict(f) for f in (faqs or [])],
    )


class WordPressConnector:
    def __init__(self, config: WPConfig):
        if not config.base_url or not config.username or not config.app_password:
            raise ValueError("WP base_url/username/app_password required")
        self.cfg = config
        self.session = requests.Session()
        self.session.headers.update(config.auth_header())
    def _url(self, path: str) -> str:
        return f"{self.cfg.base_url}/wp-json/wp/v2{path}"

    # --- reads ---

    def list_posts(self, per_page: int = 20, search: str = "") -> list[dict]:
        params = {"per_page": per_page}
        if search:
            params["search"] = search
        resp = self.session.get(self._url("/posts"), params=params, timeout=self.cfg.timeout)
        resp.raise_for_status()
        return resp.json()

    def fetch_internal_links(self, query: str, per_page: int = 10) -> list[dict]:
        """Generalize fetch_internal_links_tool to WP REST (§5.11)."""
        posts = self.list_posts(per_page=per_page, search=query)
        links = []
        for p in posts:
            slug = p.get("slug", "")
            links.append({
                "title": (p.get("title") or {}).get("rendered", ""),
                "url": f"{self.cfg.base_url}/{slug}",
                "slug": slug,
            })
        return links

    def existing_slugs(self, per_page: int = 100) -> set[str]:
        return {p.get("slug", "") for p in self.list_posts(per_page=per_page)}

    # --- taxonomy ---

    def _ensure_term(self, kind: str, name: str) -> int:
        """kind: categories|tags. Created on demand from brief mapping."""
        resp = self.session.get(self._url(f"/{kind}"), params={"search": name}, timeout=self.cfg.timeout)
        resp.raise_for_status()
        for term in resp.json():
            if (term.get("name", "") or "").lower() == name.lower():
                return term["id"]
        created = self.session.post(self._url(f"/{kind}"), json={"name": name}, timeout=self.cfg.timeout)
        created.raise_for_status()
        return created.json()["id"]

    def default_category(self) -> str:
        """Name of the site's default category — zero-manual fallback when
        the brief carries no categories (WP would assign it silently anyway;
        surfacing the name keeps the taxonomy explicit and verifiable).
        Needs an Administrator app password (reads /wp/v2/settings)."""
        resp = self.session.get(self._url("/settings"), timeout=self.cfg.timeout)
        resp.raise_for_status()
        cat_id = (resp.json() or {}).get("default_category")
        if not cat_id:
            return ""
        cat = self.session.get(self._url(f"/categories/{cat_id}"), timeout=self.cfg.timeout)
        cat.raise_for_status()
        return (cat.json().get("name") or "").strip()

    # --- media ---

    def upload_media(self, path: str, alt: str = "") -> dict:
        mime, _ = mimetypes.guess_type(path)
        with open(path, "rb") as fh:
            data = fh.read()
        filename = os.path.basename(path)
        resp = self.session.post(
            self._url("/media"),
            headers={"Content-Disposition": f"attachment; filename={filename}",
                      "Content-Type": mime or "image/jpeg"},
            data=data,
            timeout=self.cfg.timeout,
        )
        resp.raise_for_status()
        media = resp.json()
        if alt:
            self.session.post(self._url(f"/media/{media['id']}"),
                              json={"alt_text": alt}, timeout=self.cfg.timeout)
        return {"id": media["id"], "url": media.get("source_url", "")}

    # --- guards ---

    def pre_publish_checks(self, post: PreparedPost) -> dict:
        """Duplicate prevention + outbound 200-check + slug collision.

        `WP_LINK_CHECK=0|off|false` skips the outbound HEAD/sanity check
        (dev/acceptance runs on a fresh local site where AI-written links
        may 403 or point at slugs that don't exist yet — fail-open opt-out;
        default stays ON for production).
        """
        taken = self.existing_slugs()
        slug = next_available_slug(post.slug or post.title, taken)
        skip = (os.environ.get("WP_LINK_CHECK") or "").strip().lower() in ("0", "off", "false")
        if skip:
            validation = {"has_invalid": False, "invalid_internal": [], "invalid_external": []}
        else:
            validation = validate_links(post.markdown or post.html)
        return {
            "slug": slug,
            "duplicate": (post.slug or post.title) in taken,
            "has_invalid_links": validation["has_invalid"],
            "invalid": validation["invalid_internal"] + validation["invalid_external"],
        }

    def _meta_payload(self, post: PreparedPost) -> dict:
        """Yoast / Rank Math / AIOSEO fields + canonical. JSON-LD is injected
        into the body (see publish) since WP REST won't render a schema meta)."""
        return {
            "meta": {
                "_yoast_wpseo_title": post.meta_title,
                "_yoast_wpseo_metadesc": post.meta_description,
                "_yoast_wpseo_focuskw": post.focus_keyphrase,
                "_yoast_wpseo_canonical": post.canonical,
                "rank_math_title": post.meta_title,
                "rank_math_description": post.meta_description,
                "rank_math_focus_keyword": post.focus_keyphrase,
                "rank_math_canonical_url": post.canonical,
                "_aioseo_title": post.meta_title,
                "_aioseo_description": post.meta_description,
            }
        }

    # --- publish ---

    def publish(self, post: PreparedPost, mode: str = "draft") -> dict:
        """mode: draft (default for new sites) | auto (publish now)."""
        checks = self.pre_publish_checks(post)
        if checks["has_invalid_links"]:
            raise ValueError(f"blocked: {len(checks['invalid'])} invalid outbound link(s)")
        post.slug = checks["slug"]

        body = post.html
        featured_id = None
        if post.featured_image_path:
            media = self.upload_media(post.featured_image_path, post.featured_alt)
            featured_id = media["id"]

        # §5.11 in-post images at H2 breaks: upload any local-path images,
        # then inject at their placement; append Article + FAQ JSON-LD.
        uploaded_inpost = []
        for img in post.inpost_images:
            src = img.get("url") or img.get("src")
            if not src and img.get("path"):
                src = self.upload_media(img["path"], img.get("alt", ""))["url"]
            if src:
                uploaded_inpost.append({
                    "url": src, "alt": img.get("alt", ""), "after_h2": img.get("after_h2"),
                })
        base = wp_render.inject_inpost_images(body, uploaded_inpost)
        ld = wp_render.jsonld_script(post.article_schema)
        if post.faq_schema:
            ld += "\n" + wp_render.jsonld_script(post.faq_schema)
        # elementor: the FAQ accordion rides as a native widget — keep it out
        # of the html widget, but leave a plain-<details> section in the
        # fallback post content so the page still has FAQs without Elementor.
        faq_html = ""
        if post.render_target == "elementor" and post.faqs:
            faq_html = wp_render.render_faq_block(post.faqs, blocks=False)
        body = base + (("\n" + faq_html) if faq_html else "") + "\n" + ld

        cat_ids = [self._ensure_term("categories", c) for c in post.categories]
        tag_ids = [self._ensure_term("tags", t) for t in post.tags]

        payload = {
            "title": post.title,
            "content": body,
            "excerpt": post.excerpt,
            "slug": post.slug,
            "status": "publish" if mode == "auto" else "draft",
            "categories": cat_ids,
            "tags": tag_ids,
            **self._meta_payload(post),
        }
        if featured_id:
            payload["featured_media"] = featured_id
        resp = self.session.post(self._url("/posts"), json=payload, timeout=self.cfg.timeout)
        resp.raise_for_status()
        doc = resp.json()
        result = {"id": doc["id"], "url": doc.get("link", ""), "slug": post.slug, "status": payload["status"]}
        if featured_id:
            result["featured_media"] = featured_id
        if post.render_target == "elementor":
            # Post exists first (content = plain HTML fallback) → an Elementor
            # failure leaves a valid standard post, never a duplicate. The FAQ
            # accordion widget is built from post.faqs (not the body HTML).
            result["elementor"] = self._write_elementor(
                doc["id"], post.title, base + "\n" + ld, faqs=post.faqs)
        return result

    def _write_elementor(self, post_id: int, title: str, body_html: str,
                         faqs: list | None = None) -> dict:
        """Elementor document write. Fail-open by design: the post already
        exists — report the error, never re-create or raise."""
        from lib.elementor import ElementorClient, build_blog_page_data  # local: no import cycle
        try:
            return ElementorClient(self.cfg).save_document(
                post_id,
                build_blog_page_data(title, body_html, faqs=faqs),
                page_settings={"hide_title": "yes"},  # heading widget carries the H1
            )
        except Exception as exc:  # noqa: BLE001 — fail-open contract
            return {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "fallback": "post content already saved as standard HTML — edit in Gutenberg or retry the elementor write",
            }

    def refresh(self, post_id: int, html: str | None = None, featured_image_path: str | None = None) -> dict:
        """Refresh path: bumps dateModified signal via modified update."""
        payload: dict = {}
        if html is not None:
            payload["content"] = html
        if featured_image_path:
            payload["featured_media"] = self.upload_media(featured_image_path)["id"]
        resp = self.session.post(self._url(f"/posts/{post_id}"), json=payload, timeout=self.cfg.timeout)
        resp.raise_for_status()
        return resp.json()

    def update_post(self, post_id: int, post: PreparedPost,
                    body_html: str | None = None,
                    featured_image_path: str | None = None) -> dict:
        """Update an EXISTING post in place (§5.11 refresh/decay path).

        Unlike publish() this never creates and never touches status — it
        rewrites content, excerpt and the SEO meta (+ taxonomy when the brief
        has it, + featured image when given), so a refresh can't un-publish a
        live post. `body_html` overrides the prepared body (callers pass the
        assembled body with in-post images + JSON-LD already injected).
        """
        body = body_html if body_html is not None else post.html
        payload: dict = {"content": body, "excerpt": post.excerpt,
                         **self._meta_payload(post)}
        if post.categories:
            payload["categories"] = [self._ensure_term("categories", c)
                                     for c in post.categories]
        if post.tags:
            payload["tags"] = [self._ensure_term("tags", t) for t in post.tags]
        if featured_image_path:
            payload["featured_media"] = self.upload_media(
                featured_image_path, post.featured_alt)["id"]
        resp = self.session.post(self._url(f"/posts/{post_id}"), json=payload,
                                 timeout=self.cfg.timeout)
        resp.raise_for_status()
        doc = resp.json()
        return {"id": doc["id"], "url": doc.get("link", ""),
                "status": doc.get("status", ""), "slug": doc.get("slug", "")}

    def get_post(self, post_id: int, context: str = "edit") -> dict:
        """Read one post back (the WP equivalent of SanityAdapter
        `get_post_content_markdown`). `context=edit` exposes the RAW content
        and registered `meta` (Yoast/RankMath/AIOSEO) — used to verify a
        refresh, read before update, or feed decay analysis."""
        resp = self.session.get(self._url(f"/posts/{post_id}"),
                                params={"context": context}, timeout=self.cfg.timeout)
        resp.raise_for_status()
        doc = resp.json()
        title = doc.get("title") or {}
        content = doc.get("content") or {}
        excerpt = doc.get("excerpt") or {}
        return {
            "id": doc["id"],
            "slug": doc.get("slug", ""),
            "status": doc.get("status", ""),
            "title": title.get("raw") or title.get("rendered", ""),
            "content_raw": content.get("raw") or content.get("rendered", ""),
            "excerpt": excerpt.get("raw") or excerpt.get("rendered", ""),
            "url": doc.get("link", ""),
            "modified": doc.get("modified", ""),
            "featured_media": doc.get("featured_media", 0),
            "categories": doc.get("categories", []),
            "tags": doc.get("tags", []),
            "meta": doc.get("meta") or {},
        }
