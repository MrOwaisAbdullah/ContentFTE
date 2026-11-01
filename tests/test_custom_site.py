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


class _Resp:
    def __init__(self, code=202):
        self.status_code = code


def _capture(monkeypatch, codes):
    """Replace requests.post; returns the list of recorded calls. `codes` is consumed one per call
    (an Exception instance is raised instead of returned)."""
    calls, it = [], iter(codes)

    def fake_post(url, data=None, headers=None, timeout=None, allow_redirects=None, **kw):
        calls.append({"url": url, "data": data, "headers": headers, "allow_redirects": allow_redirects})
        nxt = next(it)
        if isinstance(nxt, Exception):
            raise nxt
        return _Resp(nxt)

    monkeypatch.setattr(custom_site.requests, "post", fake_post)
    return calls


def test_deliver_posts_the_canonical_body(monkeypatch):
    monkeypatch.delenv("SITE_PUBLISH_SECRET", raising=False)
    calls = _capture(monkeypatch, [202])
    out = custom_site.deliver({"title": "x", "a": 1}, webhook_url="https://hook.example/deploy", sleep=lambda s: None)
    assert out["status"] == "ok" and out["status_code"] == 202 and out["attempts"] == 1 and out["signed"] is False
    assert calls[0]["url"] == "https://hook.example/deploy"
    assert calls[0]["data"] == b'{"a":1,"title":"x"}'
    assert calls[0]["allow_redirects"] is False
    assert "X-CFTE-Signature" not in calls[0]["headers"]


def test_a_signed_delivery_verifies_and_rejects_tampering_and_replay(monkeypatch):
    calls = _capture(monkeypatch, [200])
    custom_site.deliver({"title": "x"}, webhook_url="https://hook.example/d", secret="s3cret", sleep=lambda s: None)
    h, body = calls[0]["headers"], calls[0]["data"]
    assert custom_site.verify_signature("s3cret", body, h["X-CFTE-Signature"]) is True
    assert custom_site.verify_signature("wrong", body, h["X-CFTE-Signature"]) is False
    assert custom_site.verify_signature("s3cret", body + b" ", h["X-CFTE-Signature"]) is False      # tampered body
    ts = int(h["X-CFTE-Timestamp"])
    assert custom_site.verify_signature("s3cret", body, h["X-CFTE-Signature"], now=ts + 301) is False   # replay
    assert custom_site.verify_signature("s3cret", body, "garbage") is False
    assert custom_site.verify_signature("s3cret", body, "") is False


def test_transient_failures_are_retried_with_one_delivery_id_and_a_fresh_signature(monkeypatch):
    calls = _capture(monkeypatch, [503, RuntimeError("reset"), 200])
    sleeps = []
    out = custom_site.deliver({"t": 1}, webhook_url="https://h.example/d", secret="k", sleep=sleeps.append)
    assert out["status"] == "ok" and out["attempts"] == 3 and len(sleeps) == 2
    ids = {c["headers"]["X-CFTE-Delivery"] for c in calls}
    assert len(ids) == 1 and out["delivery_id"] in ids


def test_a_client_error_is_final_and_not_retried(monkeypatch):
    calls = _capture(monkeypatch, [403, 200])
    out = custom_site.deliver({"t": 1}, webhook_url="https://h.example/d", sleep=lambda s: None)
    assert out["status"] == "error" and out["message"] == "HTTP 403" and len(calls) == 1


def test_429_is_retried_and_exhaustion_reports_the_last_error(monkeypatch):
    calls = _capture(monkeypatch, [429, 500, 502])
    out = custom_site.deliver({"t": 1}, webhook_url="https://h.example/d", sleep=lambda s: None)
    assert out["status"] == "error" and out["attempts"] == 3 and len(calls) == 3 and "502" in out["message"]


def test_deliver_reports_network_failure(monkeypatch):
    _capture(monkeypatch, [RuntimeError("connection refused")] * 3)
    out = custom_site.deliver({"title": "x"}, webhook_url="https://hook.example/deploy", sleep=lambda s: None)
    assert out["status"] == "error" and "connection refused" in out["message"]
