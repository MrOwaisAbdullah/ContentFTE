"""§5.11 WordPress rendering + prepared-post builder (pure, offline)."""
from lib import wp_render
from lib.wordpress import PreparedPost, WordPressConnector, WPConfig, build_prepared_post


# ---------------------------------------------------------------------------
# Inline + block markdown → WP-safe HTML
# ---------------------------------------------------------------------------
def test_headings_paragraph_marks():
    html = wp_render.markdown_to_wp_html(
        "# Title\n\nHello **world** and *italics* and `code`.\n\n## Sub\n"
    )
    assert "<h1>Title</h1>" in html
    assert "<h2>Sub</h2>" in html
    assert "<strong>world</strong>" in html
    assert "<em>italics</em>" in html
    assert "<code>code</code>" in html


def test_links_images_highlight_strike():
    html = wp_render.markdown_to_wp_html(
        "See [the guide](https://x.com/g \"Guide\") and ![logo](/img.png).\n\n"
        "This is ==important== and ~~gone~~."
    )
    assert '<a href="https://x.com/g" title="Guide">the guide</a>' in html
    assert '<img src="/img.png" alt="logo">' in html
    assert "<mark>important</mark>" in html
    assert "<del>gone</del>" in html


def test_shortcode_safe_escapes_bare_brackets():
    html = wp_render.markdown_to_wp_html("Use [gallery] carefully.")
    assert "[gallery]" not in html
    assert "&#91;gallery&#93;" in html


def test_xss_escaped():
    html = wp_render.markdown_to_wp_html("<script>alert(1)</script>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_lists_nested_and_ordered():
    html = wp_render.markdown_to_wp_html(
        "- one\n- two\n  - nested a\n  - nested b\n\n1. first\n2. second"
    )
    assert html.count("<ul>") == 2
    assert "<li>one</li>" in html
    assert "<li>two<ul><li>nested a</li><li>nested b</li></ul></li>" in html
    assert "<ol><li>first</li><li>second</li></ol>" in html


def test_blockquote_code_table_hr():
    md = (
        "> quoted line\n\n```python\nprint('<x>')\n```\n\n"
        "| A | B |\n|---|---|\n| 1 | **2** |\n\n---\n"
    )
    html = wp_render.markdown_to_wp_html(md)
    assert '<blockquote class="wp-block-quote"><p>quoted line</p></blockquote>' in html
    assert '<pre class="wp-block-code"><code>' in html
    assert "print(&#x27;&lt;x&gt;&#x27;)" in html
    assert "<table><thead><tr><th>A</th><th>B</th></tr></thead>" in html
    assert "<td><strong>2</strong></td>" in html
    assert "<hr>" in html


# ---------------------------------------------------------------------------
# Gutenberg block mode (default) — no manual "Convert to Blocks" needed
# ---------------------------------------------------------------------------
def test_block_mode_default_wraps_every_element():
    html = wp_render.markdown_to_wp_html(
        "# T\n\nPara.\n\n### Deep\n\n- a\n\n1. b\n\n---\n"
    )
    assert '<!-- wp:heading {"level":1} -->\n<h1>T</h1>\n<!-- /wp:heading -->' in html
    assert '<!-- wp:heading {"level":3} -->\n<h3>Deep</h3>' in html
    assert "<!-- wp:paragraph -->\n<p>Para.</p>\n<!-- /wp:paragraph -->" in html
    assert "<!-- wp:list -->\n<ul><li>a</li></ul>\n<!-- /wp:list -->" in html
    assert '<!-- wp:list {"ordered":true} -->\n<ol><li>b</li></ol>' in html
    assert "<!-- wp:html -->\n<hr>\n<!-- /wp:html -->" in html


def test_block_mode_table_quote_code_markups():
    html = wp_render.markdown_to_wp_html(
        "> q\n\n```py\nx = 1\n```\n\n| A | B |\n|---|---|\n| 1 | 2 |\n"
    )
    assert '<!-- wp:table -->\n<figure class="wp-block-table"><table>' in html
    assert '<blockquote class="wp-block-quote"><p>q</p></blockquote>' in html
    assert '<pre class="wp-block-code"><code>x = 1</code></pre>' in html
    assert "language-py" not in html  # language class would invalidate the block


def test_blocks_false_returns_plain_html():
    html = wp_render.markdown_to_wp_html("# T\n\nPara.\n\n```js\nx\n```\n", blocks=False)
    assert "<!-- wp:" not in html
    assert "<h1>T</h1>" in html
    assert '<pre><code class="language-js">' in html


def test_faq_is_details_blocks_and_cta_is_html_block():
    faq = wp_render.render_faq_block([{"question": "Q?", "answer": "A."}])
    # native accordion: core/details blocks (bare comment attrs — sourced
    # summary/name and default showContent are omitted by the serializer)
    assert "<!-- wp:heading -->" in faq
    assert "<!-- wp:details -->" in faq
    assert '<details class="wp-block-details" name="contentfte-faq">' in faq
    assert "<summary>Q?</summary>" in faq
    assert "<!-- wp:paragraph -->" in faq
    assert "<!-- wp:html -->" not in faq
    cta = wp_render.render_cta_block("Go", "https://x.com")
    assert cta.startswith("<!-- wp:html -->")


def test_inject_images_inside_block_mode():
    body = wp_render.markdown_to_wp_html("# H1\n\ntext\n\n## One\n\nmore")
    out = wp_render.inject_inpost_images(body, [
        {"url": "/1.jpg", "alt": "in", "after_h2": 1},
    ])
    # image inserted AFTER the heading block's closing comment, wrapped as core/image
    assert "</h2>\n<!-- /wp:heading -->\n<!-- wp:image -->" in out
    assert '<img src="/1.jpg" alt="in" />' in out


# ---------------------------------------------------------------------------
# Composed blocks
# ---------------------------------------------------------------------------
def test_faq_block_and_cta():
    faq = wp_render.render_faq_block([{"question": "What is X?", "answer": "A thing."}])
    assert "<!-- wp:details -->" in faq
    assert "Frequently Asked Questions" in faq
    assert "What is X?" in faq and "A thing." in faq
    assert "faq-block" not in faq  # blocks mode has no wrapper section
    cta = wp_render.render_cta_block("Try it", "https://x.com", "Get started", is_client_owned=False)
    assert 'rel="sponsored"' in cta
    assert 'href="https://x.com"' in cta


def test_faq_plain_html_mode_is_details_accordion():
    plain = wp_render.render_faq_block(
        [{"question": "Q1?", "answer": "One.\n\nTwo."}], blocks=False)
    assert plain.startswith('<section class="faq-block">')
    assert plain.count("<details") == 1
    assert '<details class="faq-item" name="contentfte-faq">' in plain
    assert "<summary>Q1?</summary>" in plain
    assert plain.count("<p>") == 2  # blank-line split → two paragraph tags
    assert "<!-- wp:" not in plain
    # empty faqs renders nothing at all
    assert wp_render.render_faq_block([]) == ""
    assert wp_render.render_faq_block([{"question": "  ", "answer": "x"}]) == ""


def test_inject_inpost_images_after_h2_and_trailing():
    body = "<h2>One</h2><p>a</p><h2>Two</h2><p>b</p>"
    out = wp_render.inject_inpost_images(body, [
        {"url": "/1.jpg", "alt": "first", "after_h2": 1},
        {"url": "/2.jpg", "alt": "second", "after_h2": 2},
        {"url": "/3.jpg", "alt": "tail", "after_h2": 9},
    ])
    assert out.index("/1.jpg") < out.index("<h2>Two</h2>")
    assert out.index("/2.jpg") > out.index("<h2>Two</h2>")
    assert out.rstrip().endswith("</figure>")  # out-of-range image appended


def test_jsonld_script():
    assert wp_render.jsonld_script(None) == ""
    s = wp_render.jsonld_script({"@type": "Article"})
    assert s.startswith('<script type="application/ld+json">')
    assert '"@type": "Article"' in s


# ---------------------------------------------------------------------------
# Prepared-post builder + connector wiring
# ---------------------------------------------------------------------------
def test_build_prepared_post_composes_body_and_schema():
    post = build_prepared_post(
        title="My Post", markdown="# Body\n\nText.",
        url="https://x.com/my-post",
        faqs=[{"question": "Q?", "answer": "A."}],
        cta={"label": "Go", "url": "https://x.com/go", "text": "CTA"},
        categories=["SEO"], tags=["ai"],
    )
    assert isinstance(post, PreparedPost)
    assert "<h1>Body</h1>" in post.html
    assert "<!-- wp:details -->" in post.html
    assert "<summary>Q?</summary>" in post.html
    assert 'class="cta-block"' in post.html
    assert post.faq_schema["@type"] == "FAQPage"
    assert post.article_schema["@type"] == "Article"
    assert post.meta_title == "My Post"


def test_meta_payload_covers_all_seo_plugins():
    conn = WordPressConnector(WPConfig(base_url="https://x", username="u", app_password="p"))
    post = PreparedPost(title="T", html="<p>x</p>", meta_title="MT",
                        meta_description="MD", canonical="https://x/c")
    meta = conn._meta_payload(post)["meta"]
    for key in ("_yoast_wpseo_title", "rank_math_title", "_aioseo_title"):
        assert meta[key] == "MT"
    assert meta["_yoast_wpseo_canonical"] == "https://x/c"


def test_publish_injects_images_schema_and_meta(monkeypatch):
    conn = WordPressConnector(WPConfig(base_url="https://x", username="u", app_password="p"))

    class _Resp:
        def __init__(self, j):
            self._j = j

        def raise_for_status(self):
            pass

        def json(self):
            return self._j

    recorded = {}

    class FakeSession:
        headers = {}

        def post(self, url, json=None, **k):
            recorded["url"] = url
            recorded["payload"] = json
            return _Resp({"id": 7, "link": "https://x/7"})

        def get(self, url, **k):
            return _Resp([])

    conn.session = FakeSession()
    conn.pre_publish_checks = lambda post: {
        "slug": "my-post", "duplicate": False, "has_invalid_links": False, "invalid": [],
    }
    conn.upload_media = lambda path, alt="": {"id": 99, "url": "https://x/media/1.jpg"}
    conn._ensure_term = lambda kind, name: 1

    post = build_prepared_post(
        title="My Post", markdown="# H\n\ntext",
        faqs=[{"question": "Q", "answer": "A"}],
        featured_image_path="/tmp/hero.jpg",
        inpost_images=[{"path": "/tmp/in.jpg", "alt": "in", "after_h2": 1}],
    )
    result = conn.publish(post, mode="auto")

    body = recorded["payload"]["content"]
    assert 'src="https://x/media/1.jpg"' in body        # in-post image uploaded + injected
    assert 'type="application/ld+json"' in body           # schema present
    assert recorded["payload"]["featured_media"] == 99    # featured set
    assert recorded["payload"]["status"] == "publish"
    assert recorded["payload"]["meta"]["_yoast_wpseo_title"] == "My Post"
    assert result["status"] == "publish"
