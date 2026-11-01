"""Plan ADP-03 / 06 / 10 / 11 / 12: WordPress and Sanity adapter robustness."""
from __future__ import annotations

import pytest

from lib.geo import next_available_slug, slugify_taxonomy
from lib.wordpress import WordPressConnector, WPConfig


class Resp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body, headers or {}
        self.ok = status < 400

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"{self.status_code}")


class FakeSession:
    def __init__(self, gets=None, posts=None):
        self.headers = {}
        self.gets, self.posts = list(gets or []), list(posts or [])
        self.calls = []

    def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        return self.gets.pop(0)

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        return self.posts.pop(0)


def connector(**kw):
    c = WordPressConnector(WPConfig(base_url="https://wp.test", username="u", app_password="p"))
    c.session = FakeSession(**kw)
    return c


# ------------------------------------------------------------------ ADP-03: terms
def test_an_existing_term_with_html_encoded_name_is_found_not_recreated():
    c = connector(gets=[Resp(200, [{"id": 9, "name": "Tips &amp; Tricks"}])])
    assert c._ensure_term("categories", "Tips & Tricks") == 9
    assert not [x for x in c.session.calls if x[0] == "POST"]          # nothing created


def test_term_exists_on_create_reuses_the_existing_id_instead_of_aborting_the_publish():
    c = connector(gets=[Resp(200, [])],
                  posts=[Resp(400, {"code": "term_exists", "data": {"term_id": 77}})])
    assert c._ensure_term("tags", "Race") == 77


def test_other_create_failures_still_raise():
    import requests
    c = connector(gets=[Resp(200, [])], posts=[Resp(400, {"code": "rest_cannot_create"})])
    with pytest.raises(requests.HTTPError):
        c._ensure_term("tags", "x")


def test_a_new_term_is_created_normally():
    c = connector(gets=[Resp(200, [{"id": 1, "name": "Other"}])], posts=[Resp(201, {"id": 5})])
    assert c._ensure_term("categories", "Fresh") == 5


# ------------------------------------------------------------------ ADP-10: links and slugs
def test_internal_links_use_the_real_permalink():
    c = connector(gets=[Resp(200, [{"slug": "hello", "link": "https://wp.test/2026/05/hello/",
                                    "title": {"rendered": "Hello"}},
                                   {"slug": "old", "title": {"rendered": "Old"}}])])
    links = c.fetch_internal_links("hello")
    assert links[0]["url"] == "https://wp.test/2026/05/hello/"          # not base/slug
    assert links[1]["url"] == "https://wp.test/old"                     # fallback when WP omits `link`


def test_existing_slugs_pages_through_and_includes_drafts():
    full = [{"slug": f"p{i}"} for i in range(100)]
    c = connector(gets=[Resp(200, full), Resp(200, [{"slug": "draft-one"}])])
    slugs = c.existing_slugs()
    assert "p99" in slugs and "draft-one" in slugs and len(slugs) == 101
    first, second = c.session.calls[0][2]["params"], c.session.calls[1][2]["params"]
    assert "draft" in first["status"] and second["page"] == 2


def test_existing_slugs_stops_on_a_short_page():
    c = connector(gets=[Resp(200, [{"slug": "a"}])])
    assert c.existing_slugs() == {"a"}
    assert len(c.session.calls) == 1


# ------------------------------------------------------------------ ADP-12: media upload
def test_media_upload_sends_a_safe_content_disposition_and_the_sniffed_type(tmp_path):
    jpeg = tmp_path / "my photo é.png"                             # spaces, non-ASCII, and the wrong extension
    jpeg.write_bytes(b"\xff\xd8\xff\xe0" + b"0" * 64)                   # actually a JPEG
    c = connector(posts=[Resp(201, {"id": 3, "source_url": "https://wp.test/m.jpg"}), Resp(200, {})])
    out = c.upload_media(str(jpeg), alt="a photo")
    hdr = c.session.calls[0][2]["headers"]
    assert hdr["Content-Type"] == "image/jpeg"                           # bytes win over the .png name
    disp = hdr["Content-Disposition"]
    assert disp.startswith('attachment; filename="my photo .png"')
    assert "filename*=UTF-8''my%20photo%20%C3%A9.png" in disp
    assert out == {"id": 3, "url": "https://wp.test/m.jpg"}


def test_a_quote_in_the_filename_cannot_break_out_of_the_header(tmp_path, monkeypatch):
    import os
    img = tmp_path / "plain.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    monkeypatch.setattr(os.path, "basename", lambda p: 'evil"; name.png')   # not creatable on Windows
    c = connector(posts=[Resp(201, {"id": 3})])
    c.upload_media(str(img))
    disp = c.session.calls[0][2]["headers"]["Content-Disposition"]
    quoted = disp.split("filename=", 1)[1].split(";", 1)[0] if False else disp.split('filename="', 1)[1].split('"', 1)[0]
    assert '"' not in quoted and quoted == "evil; name.png"
    assert "%22" in disp                                                  # the quote survives, encoded, in filename*


def test_a_failed_alt_text_write_is_logged_not_ignored(tmp_path, caplog):
    img = tmp_path / "a.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    c = connector(posts=[Resp(201, {"id": 4}), Resp(403, {})])
    with caplog.at_level("WARNING"):
        c.upload_media(str(img), alt="alt text")
    assert any("alt text not saved" in r.message for r in caplog.records)


# ------------------------------------------------------------------ ADP-11: unicode slugs
def test_ascii_slugs_are_unchanged():
    assert slugify_taxonomy("Python & AI Tips!") == "python-ai-tips"
    assert slugify_taxonomy("  Hello   World  ") == "hello-world"
    assert slugify_taxonomy("") == "uncategorized" and slugify_taxonomy("!!!") == "uncategorized"


@pytest.mark.parametrize("title", ["اردو ٹیک", "人工智能 教程",
                                   "Café Culture", "агенты"])
def test_non_latin_titles_keep_their_letters_instead_of_collapsing(title):
    slug = slugify_taxonomy(title)
    assert slug != "uncategorized" and slug and " " not in slug


def test_different_non_latin_categories_get_different_slugs():
    taken = set()
    a = next_available_slug("اردو", taken)
    taken.add(a)
    b = next_available_slug("人工智能", taken)
    assert a != b and "uncategorized" not in (a, b)


# ------------------------------------------------------------------ ADP-06: Sanity retries
def make_sanity(monkeypatch, statuses, headers=None):
    import lib.sanity_adapter as sa
    sleeps, calls = [], []
    monkeypatch.setattr(sa.time, "sleep", lambda s: sleeps.append(s))
    it = iter(statuses)

    class R:
        def __init__(self, code):
            self.status_code = code
            self.headers = headers or {}

    def fake_request(method, url, **kw):
        calls.append(url)
        return R(next(it))

    monkeypatch.setattr(sa.requests, "request", fake_request)
    ad = sa.SanityAdapter.__new__(sa.SanityAdapter)
    ad.base_url, ad.headers, ad.api_version = "https://x.api.sanity.io", {"Authorization": "Bearer t"}, "v2024-01-01"
    return ad, sleeps, calls


def test_sanity_retries_rate_limits_and_transient_errors(monkeypatch):
    ad, sleeps, calls = make_sanity(monkeypatch, [429, 503, 200])
    assert ad._make_request("POST", "/q", data={"a": 1}, max_retries=3).status_code == 200
    assert len(calls) == 3 and len(sleeps) == 2


def test_sanity_honours_retry_after_but_caps_it(monkeypatch):
    ad, sleeps, _ = make_sanity(monkeypatch, [429, 200], headers={"Retry-After": "3"})
    ad._make_request("GET", "/q", max_retries=3)
    assert sleeps == [3.0]
    ad, sleeps, _ = make_sanity(monkeypatch, [429, 200], headers={"Retry-After": "9999"})
    ad._make_request("GET", "/q", max_retries=3)
    assert sleeps == [30.0]


def test_sanity_gives_the_last_response_back_when_retries_run_out(monkeypatch):
    ad, sleeps, calls = make_sanity(monkeypatch, [503, 503, 503])
    assert ad._make_request("GET", "/q", max_retries=3).status_code == 503
    assert len(calls) == 3


def test_sanity_does_not_retry_client_errors_or_success(monkeypatch):
    ad, sleeps, calls = make_sanity(monkeypatch, [404])
    assert ad._make_request("GET", "/q", max_retries=3).status_code == 404
    assert calls == ["https://x.api.sanity.io/q"] and sleeps == []


def test_sanity_with_a_single_attempt_does_not_retry(monkeypatch):
    ad, sleeps, calls = make_sanity(monkeypatch, [429])
    assert ad._make_request("GET", "/q", max_retries=1).status_code == 429
    assert len(calls) == 1 and sleeps == []


def test_post_blog_reports_the_real_error_not_an_unbound_local(monkeypatch):
    import lib.sanity_adapter as sa
    ad = sa.SanityAdapter.__new__(sa.SanityAdapter)

    def boom(*a, **k):
        raise RuntimeError("author lookup failed")
    ad.ensure_document_exists = boom
    out = ad.post_blog("T", "s", "body", [], "", "my-slug", "alt", [])
    assert out["status"] == "error" and "author lookup failed" in out["error"]
    assert out["post_url"].endswith("my-slug")


# ---- ADP-02: the WordPress inline renderer ----------------------------------------------------------
def test_linked_image_keeps_the_image_and_leaks_no_placeholder():
    from lib.wp_render import inline
    out = inline("[![alt](https://x.com/a.png)](https://y.com)")
    assert "\x00" not in out
    assert out == '<a href="https://y.com"><img src="https://x.com/a.png" alt="alt"></a>'


def test_code_spans_are_literal_and_do_not_mis_nest_with_emphasis():
    from lib.wp_render import inline
    assert inline("a `**x**` b `**y**` c") == "a <code>**x**</code> b <code>**y**</code> c"
    # a shortcode inside code must stay inert in WordPress
    assert "[gallery]" not in inline("`[gallery]`")


def test_link_labels_render_inline_marks_and_urls_keep_balanced_parentheses():
    from lib.wp_render import inline
    assert inline("[**bold** link](https://e.com/Foo_(bar))") == \
        '<a href="https://e.com/Foo_(bar)"><strong>bold</strong> link</a>'
    assert inline("[x](javascript:alert(1))") == "x"          # still never a live link


def test_two_sublists_under_one_item_are_both_kept():
    from lib.wp_render import markdown_to_wp_html
    html = markdown_to_wp_html("- a\n  - b\n  1. c\n- d", blocks=False)
    assert "<li>b</li>" in html and "<li>c</li>" in html


# ---- SEO-12: link validator ---------------------------------------------------------------------------
def test_soft_404_detection():
    from lib.link_validator import _is_soft_404
    assert _is_soft_404("https://e.com/blog/made-up", "https://e.com/") is True           # deep link -> homepage
    assert _is_soft_404("https://e.com/blog/made-up", "https://www.e.com/") is True
    assert _is_soft_404("https://e.com/a", "https://e.com/404") is True
    assert _is_soft_404("https://e.com/a", "https://e.com/a/") is False                   # trailing slash only
    assert _is_soft_404("https://e.com/old", "https://e.com/new-page") is False           # a real move
    assert _is_soft_404("https://e.com/", "https://e.com/en/") is False
    assert _is_soft_404("https://e.com/a", "https://other.com/") is False                 # another site's root


def test_a_bot_blocked_link_is_kept_not_stripped(monkeypatch):
    import lib.link_validator as lv
    monkeypatch.setattr(lv, "_head_ok", lambda url, timeout=8.0: (False, 403 if "blocked" in url else 404))
    md = "[a](https://blocked.test/x) and [b](https://gone.test/y)"
    res = lv.validate_links(md, known_internal_slugs=[], check_external_head=True)
    by = {e["url"]: e for e in res["external"]}
    assert by["https://blocked.test/x"]["valid"] is True and by["https://blocked.test/x"]["unverifiable"] is True
    assert by["https://gone.test/y"]["valid"] is False
    stripped = lv.strip_invalid_links(md, res)
    assert "[a](https://blocked.test/x)" in stripped and "[b](" not in stripped


# ---- ADP-15: per-site IndexNow / Bing keys ------------------------------------------------------------
def test_each_site_uses_its_own_indexnow_key_and_shared_mode_ignores_the_global_one(monkeypatch):
    import lib.indexing as ix
    calls = []
    monkeypatch.setattr(ix, "submit_indexnow", lambda urls, base_url, key: calls.append(("nb", base_url, key)) or {"ok": True})
    monkeypatch.setattr(ix, "submit_bing_wmt", lambda urls, site_url, api_key: calls.append(("bing", site_url, api_key)) or {"ok": True})
    monkeypatch.setenv("INDEXING_ENABLED", "1")
    monkeypatch.setenv("INDEXNOW_KEY", "GLOBAL")
    monkeypatch.setenv("BING_WMT_API_KEY", "GLOBALBING")

    ix.submit_published("https://a.test/x", site_url="https://a.test", indexnow_key="A-KEY", env_fallback=False)
    assert calls == [("nb", "https://a.test", "A-KEY")]

    calls.clear()
    monkeypatch.setenv("TENANCY_MODE", "shared")
    out = ix.submit_published("https://b.test/x", site_url="https://b.test")   # no own key, shared mode
    assert calls == [] and "no IndexNow" in out["skipped"]                      # the global key would just fail

    calls.clear()
    monkeypatch.setenv("TENANCY_MODE", "isolated")
    ix.submit_published("https://c.test/x", site_url="https://c.test")          # single-site fallback still works
    assert ("nb", "https://c.test", "GLOBAL") in calls and ("bing", "https://c.test", "GLOBALBING") in calls


def test_the_service_passes_the_sites_own_keys():
    from sdk import service

    class _Site:
        settings = {"indexing": {"indexnow_key": "K1", "bing_wmt_key": "B1"}}
    assert service._indexing_keys(_Site()) == {"indexnow_key": "K1", "bing_key": "B1"}
    assert service._indexing_keys(None) == {"indexnow_key": "", "bing_key": ""}


# ---- SEO-09: the headline score is derived from the sub-scores ---------------------------------------
def test_an_inflated_overall_cannot_outrun_its_sub_scores():
    from lib.eval_gate import EvalReport, check_gate, computed_overall, effective_overall
    subs = dict.fromkeys(("accuracy", "depth", "seo", "voice", "originality", "citability"), 82)
    r = EvalReport(overall=94, sub_scores=subs)
    assert computed_overall(subs) == 82 and effective_overall(r) == 87        # mean 82 + tolerance 5
    verdict = check_gate(r)
    assert verdict["publish"] is False and "reported 94" in verdict["reasons"][0]
    honest = EvalReport(overall=91, sub_scores=dict.fromkeys(subs, 91))
    assert check_gate(honest)["publish"] is True
    assert effective_overall(EvalReport(overall=95, sub_scores={"accuracy": 99})) == 95   # incomplete: unchanged
