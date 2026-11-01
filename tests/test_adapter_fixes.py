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
