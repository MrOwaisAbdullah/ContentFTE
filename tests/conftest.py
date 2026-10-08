"""Shared pytest fixtures.

Blocks every network/credential-dependent path for the unit suite:
CI has no Cloudflare/Pexels/WP/.env credentials, but a developer's shell
(or a stray .env) might — these env vars are cleared unless
CONTENTFTE_TEST_LIVE=1, so tests can never hit a provider.

CONTENTFTE_REVISE=0 keeps generate_content single-shot: the existing fake
envelopes (~120 words, 2 FAQs, no Sources) intentionally fail the quality
checks, and a revise loop would double-run every generation test.
Revise-loop tests re-enable it via monkeypatch.setenv("CONTENTFTE_REVISE", "1").
"""
from __future__ import annotations

import os

import pytest

_LIVE = "CONTENTFTE_TEST_LIVE"

_LIVE_ON = ("1", "on", "true", "yes")

# Provider/endpoint env vars tests must never see.
_GUARDED = (
    "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID",
    "PEXELS_API_KEY",
    "WP_BASE_URL", "WP_USERNAME", "WP_APP_PASSWORD",
)


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch):
    monkeypatch.setenv("CONTENTFTE_REVISE", "0")
    if os.environ.get(_LIVE) not in _LIVE_ON:
        for key in _GUARDED:
            monkeypatch.delenv(key, raising=False)
        # Keep the JEV category judge (lib.taxonomy) offline: stub the
        # underlying call so _jev_judge swallows it -> None (propose-new
        # fallback). OPENROUTER_API_KEY itself must stay untouched — the
        # agent modules read it at import time (tools/tools.py load_dotenv).
        try:
            import lib.jev_tools as _jev_tools
            monkeypatch.setattr(_jev_tools, "jev_classify_category",
                                lambda *a, **k: "{}")
        except Exception:  # noqa: BLE001 — import fails -> _jev_judge swallows
            pass
    yield
