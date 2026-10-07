"""L80 (TASKS Phase 1B acceptance) — service.publish_article -> WordPress push.

site_type="wordpress" publishes push the article to WP in the same call
(meta description, Yoast/RankMath/AIOSEO meta, Article+FAQ JSON-LD,
categories from the brief else the site default, featured/in-post images
from meta.images). Fail-open: an unconfigured or failing WP never rolls
back the status flip; a created post is deduped via meta.wp_post_id.
Custom sites stay status-only.
"""
import os

import pytest


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch):
    import os

    workdir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           ".test-tmp-phase1")
    os.makedirs(workdir, exist_ok=True)
    db_file = os.path.join(workdir, "wp_push.db")
    try:
        os.remove(db_file)
    except OSError:
        pass
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.delenv("SDK_MASTER_KEY", raising=False)
    monkeypatch.delenv("WP_BASE_URL", raising=False)
    monkeypatch.delenv("WP_USERNAME", raising=False)
    monkeypatch.delenv("WP_APP_PASSWORD", raising=False)
    monkeypatch.delenv("WP_RENDER_TARGET", raising=False)
    monkeypatch.delenv("WP_LINK_CHECK", raising=False)
    import lib.db as db

    if db._engine is not None:
        db._engine.dispose()
    db._engine = None
    db._SessionLocal = None
    try:
        os.remove(db_file)
    except OSError:
        pass
    from sdk import service

    service.init()
    yield
    if db._engine is not None:
        db._engine.dispose()
    try:
        os.remove(db_file)
    except OSError:
        pass


class _FakeConnector:
    """Stands in for lib.wordpress.WordPressConnector (patched module-wide)."""

    instances: list = []
    default_category_name = "Uncategorized"
    publish_error: Exception | None = None

    def __init__(self, cfg):
        self.cfg = cfg
        self.published: list = []  # (post, mode)
        self.updated: list = []    # (post_id, post, body_html)
        self.default_category_calls = 0
        self.featured_existed: bool | None = None
        _FakeConnector.instances.append(self)

    def default_category(self) -> str:
        self.default_category_calls += 1
        return self.default_category_name

    def upload_media(self, path, alt=""):
        return {"id": 55, "url": "http://wp.test/media/55.jpg"}

    def update_post(self, post_id, post, body_html=None, featured_image_path=None):
        self.updated.append((post_id, post, body_html))
        return {"id": post_id, "url": f"http://wp.test/?p={post_id}",
                "status": "draft", "slug": post.slug}

    def publish(self, post, mode="draft"):
        if _FakeConnector.publish_error is not None:
            raise _FakeConnector.publish_error
        if post.featured_image_path:
            self.featured_existed = os.path.isfile(post.featured_image_path)
        else:
            self.featured_existed = None
        self.published.append((post, mode))
        return {"id": 4242, "url": "http://wp.test/?p=4242", "slug": post.slug,
                "status": "publish" if mode == "auto" else "draft",
                **({"featured_media": 7} if post.featured_image_path else {})}


@pytest.fixture(autouse=True)
def _patch_connector(monkeypatch):
    _FakeConnector.instances = []
    _FakeConnector.publish_error = None
    _FakeConnector.default_category_name = "Uncategorized"
    monkeypatch.setattr("lib.wordpress.WordPressConnector", _FakeConnector)
    return _FakeConnector


def _approved_article(*, site_type="wordpress", status="approved",
                      content="## Intro\n\nBody text for the WP push.",
                      brief=None, meta=None):
    from lib.db import Article as ArticleModel, get_session
    from sdk import service

    service.upsert_site("wp-site", site_type=site_type, base_url="http://wp.test")
    art = service.submit_article("wp-site", keyword="wp acceptance",
                                 brief=brief or {})
    s = get_session()
    try:
        row = s.get(ArticleModel, art["id"])
        row.status = status
        row.title = "WP Acceptance Post"
        row.content_md = content
        if meta:
            row.meta = {**(row.meta or {}), **meta}
        s.commit()
    finally:
        s.close()
    return art["id"]


def _wp_env(monkeypatch):
    monkeypatch.setenv("WP_BASE_URL", "http://wp.test")
    monkeypatch.setenv("WP_USERNAME", "admin")
    monkeypatch.setenv("WP_APP_PASSWORD", "xxxx xxxx xxxx xxxx")


def test_wordpress_site_publish_pushes_full_payload(monkeypatch, tmp_path):
    from lib.db import AuditLog, get_session
    from sdk import service

    _wp_env(monkeypatch)
    feat = tmp_path / "hero.jpg"
    feat.write_bytes(b"jpeg-bytes")
    inp = tmp_path / "inpost.jpg"
    inp.write_bytes(b"jpeg-bytes")
    art_id = _approved_article(
        brief={"description": "Meta description for the post.",
               "categories": ["SEO"], "tags": ["acceptance"]},
        meta={"summary": "fallback summary",
              "faqs": [{"question": "What is it?", "answer": "An acceptance run."}],
              "images": [{"slot": "featured", "path": str(feat), "alt": "hero alt"},
                         {"slot": "inpost", "path": str(inp), "alt": "in alt",
                          "after_h2": 1}]})

    out = service.publish_article(art_id, mode="draft")

    assert out["status"] == "published" and out["event"] == "article.published"
    wp = out["wp"]
    assert wp["ok"] is True and wp["post_id"] == 4242
    assert wp["featured_media"] == 7
    assert wp["categories"] == ["SEO"]

    conn = _FakeConnector.instances[-1]
    assert len(conn.published) == 1
    post, mode = conn.published[0]
    assert mode == "draft"
    assert post.categories == ["SEO"] and post.tags == ["acceptance"]
    assert post.meta_description == "Meta description for the post."
    assert post.featured_image_path == str(feat) and post.featured_alt == "hero alt"
    assert post.inpost_images == [{"path": str(inp), "alt": "in alt", "after_h2": 1}]
    assert post.article_schema is not None and post.faq_schema is not None
    assert post.render_target == "blocks"
    # default-category fallback must NOT fire when the brief has categories
    assert conn.default_category_calls == 0

    s = get_session()
    try:
        row = s.get(service.ArticleModel, art_id)
        assert row.meta["wp_post_id"] == 4242
        assert row.meta["wp_url"] == "http://wp.test/?p=4242"
        audit = s.query(AuditLog).filter(AuditLog.action == "article.publish").all()
        assert audit and audit[-1].payload["wp"]["ok"] is True
    finally:
        s.close()


def test_wordpress_unconfigured_fails_open(monkeypatch):
    from sdk import service

    art_id = _approved_article()  # fixture deleted WP_* env
    out = service.publish_article(art_id)
    assert out["status"] == "published"
    assert out["wp"]["ok"] is False
    assert "not configured" in out["wp"]["error"]
    assert _FakeConnector.instances == []


def test_custom_site_stays_status_only(monkeypatch):
    from sdk import service

    _wp_env(monkeypatch)  # even with WP configured, custom sites don't push
    art_id = _approved_article(site_type="custom")
    out = service.publish_article(art_id, mode="auto")
    assert out["status"] == "published"
    assert "wp" not in out
    assert _FakeConnector.instances == []


def test_wordpress_push_dedupes_existing_post(monkeypatch):
    from sdk import service

    _wp_env(monkeypatch)
    art_id = _approved_article(meta={"wp_post_id": 99, "wp_url": "http://wp.test/?p=99"})
    out = service.publish_article(art_id)
    assert out["wp"]["ok"] is True
    assert out["wp"]["deduplicated"] is True and out["wp"]["post_id"] == 99
    assert _FakeConnector.instances == []  # no second post, no connector call


def test_wordpress_categories_fallback_to_site_default(monkeypatch):
    from sdk import service

    _wp_env(monkeypatch)
    art_id = _approved_article(brief={"description": "No categories here."})
    out = service.publish_article(art_id)
    assert out["wp"]["ok"] is True
    assert out["wp"]["categories"] == ["Uncategorized"]
    conn = _FakeConnector.instances[-1]
    assert conn.default_category_calls == 1
    assert conn.published[0][0].categories == ["Uncategorized"]


def test_wordpress_remote_featured_downloaded_then_cleaned(monkeypatch, tmp_path):
    from sdk import service

    _wp_env(monkeypatch)
    downloaded = {"path": None}

    def fake_download(url):
        assert url == "https://cdn.test/hero.jpg"
        p = tmp_path / "dl.jpg"
        p.write_bytes(b"jpeg-bytes")
        downloaded["path"] = str(p)
        return str(p)

    monkeypatch.setattr("sdk.service._download_image", fake_download)
    art_id = _approved_article(
        meta={"images": [{"slot": "featured", "url": "https://cdn.test/hero.jpg",
                          "alt": "remote"}]})

    out = service.publish_article(art_id)
    assert out["wp"]["ok"] is True and out["wp"]["featured_media"] == 7
    conn = _FakeConnector.instances[-1]
    assert conn.published[0][0].featured_image_path == downloaded["path"]
    assert conn.featured_existed is True  # bytes were on disk during upload
    assert not os.path.exists(downloaded["path"])  # temp cleaned after publish


def test_wordpress_push_failure_keeps_status_published(monkeypatch):
    from sdk import service

    _wp_env(monkeypatch)
    _FakeConnector.publish_error = ValueError(
        "blocked: 1 invalid outbound link(s)")
    art_id = _approved_article()
    out = service.publish_article(art_id)
    assert out["status"] == "published"
    assert out["wp"]["ok"] is False
    assert "invalid outbound link" in out["wp"]["error"]
    assert "re-run publish" in out["wp"]["next"]


def test_wordpress_push_requires_content(monkeypatch):
    from sdk import service

    _wp_env(monkeypatch)
    art_id = _approved_article(content="")
    out = service.publish_article(art_id)
    assert out["status"] == "published"
    assert out["wp"]["ok"] is False
    assert "no content_md" in out["wp"]["error"]
    assert _FakeConnector.instances == []


# --- refresh / decay path (§5.11) -------------------------------------------

def test_wordpress_refresh_updates_existing_post(monkeypatch):
    from lib.db import get_session
    from sdk import service

    _wp_env(monkeypatch)
    art_id = _approved_article(
        status="published",
        brief={"description": "Updated meta description."},
        meta={"wp_post_id": 99, "wp_url": "http://wp.test/?p=99",
              "faqs": [{"question": "Q?", "answer": "A."}]})

    out = service.refresh_article(art_id)
    assert out["ok"] is True and out["event"] == "article.refreshed"
    assert out["wp_post_id"] == 99 and out["url"] == "http://wp.test/?p=99"

    conn = _FakeConnector.instances[-1]
    assert len(conn.updated) == 1 and conn.published == []
    post_id, post, body = conn.updated[0]
    assert post_id == 99
    assert post.meta_description == "Updated meta description."
    assert "<!-- wp:" in body and "application/ld+json" in body

    s = get_session()
    try:
        row = s.get(service.ArticleModel, art_id)
        # refresh must NOT un-publish
        assert row.status == "published"
        from lib.db import AuditLog
        audit = s.query(AuditLog).filter(AuditLog.action == "article.refresh").all()
        assert audit and audit[-1].payload["wp_post_id"] == 99
    finally:
        s.close()


def test_refresh_requires_wp_post_id(monkeypatch):
    from sdk import service

    _wp_env(monkeypatch)
    art_id = _approved_article(status="published")  # no meta.wp_post_id
    out = service.refresh_article(art_id)
    assert "error" in out and "wp_post_id" in out["error"]
    assert _FakeConnector.instances == []


def test_custom_site_refresh_is_pull_only(monkeypatch):
    from sdk import service

    _wp_env(monkeypatch)  # WP configured, but custom sites never push
    art_id = _approved_article(site_type="custom", status="published")
    out = service.refresh_article(art_id)
    assert out["ok"] is True and out["render_target"] == "custom"
    assert "content" in out["next"]
    assert _FakeConnector.instances == []
