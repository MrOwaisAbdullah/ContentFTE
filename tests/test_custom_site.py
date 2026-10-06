"""§5.12 custom-site (Astro/Next) delivery payload + webhook push."""
from lib import custom_site


def test_build_delivery_payload_shape():
    payload = custom_site.build_delivery_payload(
        title="My Post",
        markdown="# Heading\n\nBody with **bold**.",
        meta_description="A description",
        slug="my-post",
        url="https://site.example/blog/my-post",
        faqs=[{"question": "Q?", "answer": "A."}],
    )
    assert "<h1>Heading</h1>" in payload["html"]
    assert "<strong>bold</strong>" in payload["html"]
    assert payload["markdown"].startswith("# Heading")
    assert payload["markdown_alternate"].startswith("---")
    assert payload["schema"]["article"]["@type"] == "Article"
    assert payload["schema"]["faq"]["@type"] == "FAQPage"
    assert payload["slug"] == "my-post"


def test_deliver_without_webhook_is_error(monkeypatch):
    monkeypatch.delenv("SITE_PUBLISH_WEBHOOK", raising=False)
    out = custom_site.deliver({"title": "x"})
    assert out["status"] == "error"
    assert "webhook" in out["message"].lower()


def test_deliver_posts_payload(monkeypatch):
    recorded = {}

    class _Resp:
        status_code = 202

        def raise_for_status(self):
            pass

    def fake_post(url, json=None, timeout=None):
        recorded["url"] = url
        recorded["json"] = json
        return _Resp()

    monkeypatch.setattr(custom_site.requests, "post", fake_post)
    out = custom_site.deliver({"title": "x"}, webhook_url="https://hook.example/deploy")
    assert out == {"status": "ok", "status_code": 202}
    assert recorded["url"] == "https://hook.example/deploy"
    assert recorded["json"]["title"] == "x"


def test_deliver_reports_http_failure(monkeypatch):
    def boom(url, json=None, timeout=None):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(custom_site.requests, "post", boom)
    out = custom_site.deliver({"title": "x"}, webhook_url="https://hook.example/deploy")
    assert out["status"] == "error"
    assert "connection refused" in out["message"]
