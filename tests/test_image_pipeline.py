"""Image pipeline (spec 5.9): IPTC provenance tagging, the stock-first
in-post VLM relevancy gate, per-image cost accounting, and the
"featured images are always AI / publish-flagged-without-image" rules.

All tests are offline: VLM/Jev are monkeypatched, stock/generation hooks are
injected, and log_image_usage is stubbed so no Google Sheets network call runs.
"""
import os

import pytest
from PIL import Image

from lib import image_provenance as ip
from lib import image_vision
from tools import tools
from tools.sheet_tool import IMAGE_LOG_HEADERS


# ---------------------------------------------------------------------------
# IPTC trainedAlgorithmicMedia provenance (lib/image_provenance.py)
# ---------------------------------------------------------------------------
def _write_image(path, fmt):
    Image.new("RGB", (16, 16), (10, 20, 30)).save(str(path), fmt)
    return str(path)


def test_jpeg_tagging_roundtrip(tmp_path):
    p = _write_image(tmp_path / "a.jpg", "JPEG")
    assert ip.has_trained_algorithmic_media(open(p, "rb").read()) is False
    assert ip.tag_trained_algorithmic_media(p) is True
    data = open(p, "rb").read()
    assert ip.has_trained_algorithmic_media(data) is True
    assert b"http://ns.adobe.com/xap/1.0/" in data
    assert ip.TRAINED_ALGORITHMIC_MEDIA_URI.encode() in data
    # The injected bytes must not corrupt the JPEG.
    with Image.open(p) as im:
        im.load()
        assert im.size == (16, 16)


def test_png_tagging_roundtrip(tmp_path):
    p = _write_image(tmp_path / "a.png", "PNG")
    assert ip.tag_trained_algorithmic_media(p) is True
    data = open(p, "rb").read()
    assert ip.has_trained_algorithmic_media(data) is True
    assert b"XML:com.adobe.xmp" in data
    with Image.open(p) as im:
        im.load()
        assert im.size == (16, 16)


def test_tagging_is_idempotent(tmp_path):
    p = _write_image(tmp_path / "a.jpg", "JPEG")
    assert ip.tag_trained_algorithmic_media(p) is True
    first = open(p, "rb").read()
    assert ip.tag_trained_algorithmic_media(p) is True
    second = open(p, "rb").read()
    assert first == second
    assert second.count(ip.TRAINED_ALGORITHMIC_MEDIA_URI.encode()) == 1


def test_tag_unsupported_and_missing_are_safe(tmp_path):
    txt = tmp_path / "x.txt"
    txt.write_bytes(b"not an image")
    assert ip.tag_trained_algorithmic_media(str(txt)) is False
    assert ip.tag_trained_algorithmic_media(str(tmp_path / "nope.jpg")) is False


def test_has_helper_on_empty_bytes():
    assert ip.has_trained_algorithmic_media(b"") is False


# ---------------------------------------------------------------------------
# Stock topic-relevancy gate (lib/image_vision.score_topic_relevancy)
# ---------------------------------------------------------------------------
class _Ans:
    def __init__(self, noul):
        self.noul = noul


class _Resp:
    def __init__(self, noul, model="jev-test"):
        self.answers = {"matches_topic": _Ans(noul)}
        self.model = model
        self.usage = None


def _patch_vlm(monkeypatch, fallback=False):
    def fake(path, title="", summary=""):
        return {
            "description": "a diagram of a neural network",
            "topic_connection": "directly depicts the topic",
            "text_seen": "none",
            "style_notes": "",
            "issues": [],
            "model": "vlm-test",
            "fallback": fallback,
        }

    monkeypatch.setattr(image_vision, "describe_image_vlm", fake)


def test_score_high_passes(monkeypatch):
    _patch_vlm(monkeypatch)
    monkeypatch.setattr(image_vision, "call_jev_sync", lambda state, q: _Resp(0.95))
    out = image_vision.score_topic_relevancy("x.jpg", "neural nets", "ctx")
    assert out["score"] == 95
    assert out["passed"] is True
    assert out["fallback"] is False


def test_score_below_threshold_fails(monkeypatch):
    _patch_vlm(monkeypatch)
    monkeypatch.setattr(image_vision, "call_jev_sync", lambda state, q: _Resp(0.72))
    out = image_vision.score_topic_relevancy("x.jpg", "neural nets")
    assert out["score"] == 72
    assert out["passed"] is False
    assert out["fallback"] is False


def test_score_vlm_outage_accepts_stock(monkeypatch):
    _patch_vlm(monkeypatch, fallback=True)
    out = image_vision.score_topic_relevancy("x.jpg", "topic")
    assert out["passed"] is True
    assert out["fallback"] is True
    assert out["score"] == 100


def test_score_jev_outage_accepts_stock(monkeypatch):
    _patch_vlm(monkeypatch)

    def boom(state, q):
        raise RuntimeError("jev down")

    monkeypatch.setattr(image_vision, "call_jev_sync", boom)
    out = image_vision.score_topic_relevancy("x.jpg", "topic")
    assert out["passed"] is True
    assert out["fallback"] is True
    assert out["score"] == 100


# ---------------------------------------------------------------------------
# Per-image cost map + image_logs columns
# ---------------------------------------------------------------------------
def test_image_cost_usd_known_and_default():
    assert tools._image_cost_usd("@cf/black-forest-labs/flux-2-klein-4b") == 0.0012
    assert tools._image_cost_usd("@cf/black-forest-labs/flux-2-klein-9b") == 0.0150
    assert tools._image_cost_usd("some/unmeasured-model") == tools.IMAGE_COST_DEFAULT_USD
    assert tools._image_cost_usd(None) == tools.IMAGE_COST_DEFAULT_USD


def test_image_log_headers_include_audit_columns():
    for col in ("Cost (USD)", "Slot", "Latency (ms)", "Prompt"):
        assert col in IMAGE_LOG_HEADERS
    # Appended at the end so rows written before the change keep mapping.
    assert IMAGE_LOG_HEADERS[:8] == [
        "Timestamp", "Model", "Stage", "Subject", "Status",
        "Reference", "Latency (s)", "Detail",
    ]


# ---------------------------------------------------------------------------
# _select_inpost_image decision matrix (injected hooks, no network)
# ---------------------------------------------------------------------------
def _stub_logs(monkeypatch):
    monkeypatch.setattr(tools, "log_image_usage", lambda *a, **k: True)


def test_select_inpost_accepts_high_score_stock(tmp_path, monkeypatch):
    _stub_logs(monkeypatch)
    img = _write_image(tmp_path / "s.jpg", "JPEG")
    calls = {}

    def fetch(topic, slot):
        calls["fetch"] = slot
        return {"image_url": img, "alt_text": "stock alt", "source": "Pexels"}

    def score(path, topic, context):
        return {"score": 95, "passed": True, "fallback": False, "latency_ms": 10}

    def gen(**kw):
        calls["gen"] = kw
        return {"image_url": "AI.jpg"}

    out = tools._select_inpost_image(
        "quantum computing", "A short summary about qubits", "",
        fetch_stock=fetch, score=score, generate=gen,
    )
    assert out["source"] == "Pexels"
    assert out["slot"] == "inpost"
    assert out["relevancy_score"] == 95
    assert out["evaluation_score"] == 9.5
    assert out["alt_text"] == "A short summary about qubits"
    assert out["gate"]["decision"] == "stock_accepted"
    assert calls["fetch"] == "inpost"
    assert "gen" not in calls


def test_select_inpost_generates_below_threshold(tmp_path, monkeypatch):
    _stub_logs(monkeypatch)
    img = _write_image(tmp_path / "s.jpg", "JPEG")
    seen = {}

    def fetch(topic, slot):
        return {"image_url": img, "alt_text": "stock alt"}

    def score(path, topic, context):
        return {"score": 72, "passed": False, "fallback": False, "latency_ms": 5}

    def gen(**kw):
        seen.update(kw)
        return {"image_url": "AI.jpg", "source": "Cloudflare Workers AI (m)"}

    out = tools._select_inpost_image(
        "topic", "section summary", "",
        fetch_stock=fetch, score=score, generate=gen,
    )
    assert seen["slot"] == "inpost"
    assert seen["keyword"] == "topic"
    assert seen["summary"] == "section summary"
    assert out["image_url"] == "AI.jpg"
    assert out["slot"] == "inpost"
    assert out["alt_text"] == "section summary"
    assert out["gate"]["decision"] == "ai_generated"


def test_select_inpost_ai_when_stock_unavailable(monkeypatch):
    _stub_logs(monkeypatch)

    def fetch(topic, slot):
        return {"error": "no pexels key"}

    def gen(**kw):
        return {"image_url": "AI.jpg"}

    out = tools._select_inpost_image(
        "topic", "sum", "", fetch_stock=fetch,
        score=lambda *a: pytest.fail("must not score with no candidate"),
        generate=gen,
    )
    assert out["image_url"] == "AI.jpg"
    assert out["gate"]["decision"] == "ai_generated"


def test_select_inpost_download_failure_falls_back_to_ai(monkeypatch):
    _stub_logs(monkeypatch)
    monkeypatch.setattr(tools, "_download_image_to_temp", lambda url: None)

    def fetch(topic, slot):
        return {"image_url": "https://images.pexels.com/photos/1/x.jpg"}

    def gen(**kw):
        return {"image_url": "AI.jpg"}

    out = tools._select_inpost_image(
        "topic", "sum", "", fetch_stock=fetch,
        score=lambda *a: pytest.fail("must not score an undownloadable candidate"),
        generate=gen,
    )
    assert out["image_url"] == "AI.jpg"
    assert out["gate"]["stock_download_failed"] is True


def test_select_inpost_error_when_all_fail(monkeypatch):
    _stub_logs(monkeypatch)

    def fetch(topic, slot):
        return {"error": "stock down"}

    def gen(**kw):
        return {"error": "generation down"}

    out = tools._select_inpost_image(
        "topic", "sum", "", fetch_stock=fetch, generate=gen,
    )
    assert "error" in out
    assert out["slot"] == "inpost"
    assert out["gate"]["decision"] == "failed"


def test_select_inpost_explicit_alt_wins(tmp_path, monkeypatch):
    _stub_logs(monkeypatch)
    img = _write_image(tmp_path / "s.jpg", "JPEG")

    out = tools._select_inpost_image(
        "topic", "section summary", "explicit alt",
        fetch_stock=lambda t, s: {"image_url": img, "alt_text": "stock"},
        score=lambda *a: {"score": 99, "passed": True, "fallback": False},
        generate=lambda **k: {"image_url": "AI.jpg"},
    )
    assert out["alt_text"] == "explicit alt"


# ---------------------------------------------------------------------------
# Agent wiring: featured is always AI, no stock substitution
# ---------------------------------------------------------------------------
def _tool_names(agent):
    return {
        getattr(t, "name", None) or getattr(t, "tool_name", None)
        for t in agent.tools
    }


def test_selection_agent_has_no_stock_tool():
    from blog_agent.image_agent import image_selection_agent

    names = _tool_names(image_selection_agent)
    assert "get_stock_image_tool" not in names
    assert "generate_image_tool" in names


def test_selection_agent_instructions_never_substitute_stock():
    from blog_agent.image_agent import image_selection_agent

    txt = image_selection_agent.instructions
    assert "Never substitute stock" in txt
    assert "get_stock_image_tool" not in txt
    assert "Stock Photo" not in txt


def test_insertion_agent_uses_gated_select_tool():
    from blog_agent.image_agent import contextual_image_insertion_agent

    names = _tool_names(contextual_image_insertion_agent)
    assert "select_inpost_image_tool" in names
    assert "get_stock_image_tool" not in names
    assert "select_inpost_image_tool" in contextual_image_insertion_agent.instructions


def test_preparation_agent_drops_stock_fallback():
    from blog_agent.posting_agent import preparation_agent

    names = _tool_names(preparation_agent)
    assert "get_stock_image_tool" not in names
    txt = preparation_agent.instructions
    assert "get_stock_image_tool" not in txt
    assert "no stock fallback" in txt
