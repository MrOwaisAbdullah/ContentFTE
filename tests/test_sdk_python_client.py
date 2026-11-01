"""Plan ENG-19: the Python SDK client must not retry what cannot succeed, nor repeat what may have worked."""
from __future__ import annotations

import pytest
import requests

from sdk import python_client as pc


class Resp:
    def __init__(self, status=200, body=None, text=""):
        self.status_code, self._body, self.text = status, body if body is not None else {}, text

    def json(self):
        if self._body is None:
            raise ValueError
        return self._body


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(pc.time, "sleep", lambda s: None)
    return pc.ContentFTEClient("https://engine.test", "key", max_retries=3, backoff=0)


def script(monkeypatch, outcomes):
    calls = []
    it = iter(outcomes)

    def fake(method, url, **kw):
        calls.append((method, url, kw))
        out = next(it)
        if isinstance(out, Exception):
            raise out
        return out
    monkeypatch.setattr(pc.requests, "request", fake)
    return calls


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 422])
def test_client_errors_are_raised_immediately_with_the_servers_reason(client, monkeypatch, status):
    calls = script(monkeypatch, [Resp(status, {"detail": "quality gate failed: 2 claims"})] * 3)
    with pytest.raises(requests.HTTPError) as exc:
        client.get_article(1)
    assert len(calls) == 1                                            # was retried 3 times
    assert str(status) in str(exc.value) and "quality gate failed" in str(exc.value)
    assert exc.value.response.status_code == status


def test_a_non_json_error_body_still_produces_a_useful_error(client, monkeypatch):
    script(monkeypatch, [Resp(404, None, text="<html>nope</html>")])
    with pytest.raises(requests.HTTPError, match="404"):
        client.get_article(1)


def test_reads_are_retried_on_transient_failures_then_succeed(client, monkeypatch):
    calls = script(monkeypatch, [Resp(503), Resp(502), Resp(200, {"id": 1})])
    assert client.get_article(1) == {"id": 1}
    assert len(calls) == 3


def test_reads_retry_after_network_errors(client, monkeypatch):
    calls = script(monkeypatch, [requests.ConnectionError("down"), Resp(200, {"ok": True})])
    assert client.get_article(1) == {"ok": True} and len(calls) == 2


def test_a_post_is_not_repeated_after_an_ambiguous_5xx_without_an_idempotency_key(client, monkeypatch):
    calls = script(monkeypatch, [Resp(503), Resp(200, {"status": "published"})])
    with pytest.raises(requests.HTTPError):
        client.publish_article(7)
    assert len(calls) == 1                     # a 2nd POST could have published twice


def test_a_post_is_not_repeated_after_a_timeout_without_a_key(client, monkeypatch):
    calls = script(monkeypatch, [requests.ReadTimeout("slow"), Resp(200, {})])
    with pytest.raises(requests.ReadTimeout):
        client.generate_content(7)
    assert len(calls) == 1                     # the first call may still be running server-side


def test_a_post_with_an_idempotency_key_is_safe_to_repeat(client, monkeypatch):
    calls = script(monkeypatch, [requests.ReadTimeout("slow"), Resp(503), Resp(200, {"id": 5})])
    out = client.submit_article("s", keyword="k", idempotency_key="abc")
    assert out == {"id": 5} and len(calls) == 3
    assert all(c[2]["headers"]["Idempotency-Key"] == "abc" for c in calls)


def test_429_is_always_repeated_because_the_request_was_not_processed(client, monkeypatch):
    calls = script(monkeypatch, [Resp(429), Resp(200, {"status": "published"})])
    assert client.publish_article(7) == {"status": "published"}
    assert len(calls) == 2


def test_retries_give_up_after_max_attempts(client, monkeypatch):
    calls = script(monkeypatch, [Resp(503)] * 5)
    with pytest.raises(requests.HTTPError, match="503"):
        client.get_article(1)
    assert len(calls) == 3
