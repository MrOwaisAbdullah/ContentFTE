"""Keep credentials out of logs (plan SEC-11).

Three places were writing secrets or whole articles to logs: the Sanity adapter printed every request
body and logged its request headers (which hold `Authorization: Bearer <SANITY_API_TOKEN>`), the
IndexNow/Bing helpers put the API key in the URL and returned exception text that quotes that URL, and
the agent hooks printed every tool result in full — into public GitHub Actions logs.

Pure functions, no I/O. They are conservative on purpose: anything that *looks* like a credential is
masked, because a log line that hides a harmless value is cheaper than one that leaks a token.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

MASK = "***"
_SENSITIVE_KEY = re.compile(
    r"(authorization|api[_-]?key|x-site-key|token|secret|password|passwd|cookie|credential|webhook)", re.I)

# `Bearer abc.def`, `apikey=abc`, `?key=abc`, `token: abc`, `"password": "abc"`
_PATTERNS = [
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{6,}"), r"\1 " + MASK),
    (re.compile(r"(?i)([?&;\s](?:api[_-]?key|apikey|key|token|access_token|secret|password)=)[^&\s\"']+"),
     r"\1" + MASK),
    (re.compile(r"(?i)(\"?(?:api[_-]?key|token|secret|password|authorization|x-site-key)\"?\s*[:=]\s*\"?)"
                r"[^\"\s,}&]{4,}"), r"\1" + MASK),
    # credentials in a URL's userinfo: postgresql://user:SECRET@host/db  (DB errors quote these)
    (re.compile(r"(\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s:/@]*):[^\s@/]+@"), r"\1:" + MASK + "@"),
    (re.compile(r"\bcfte_[A-Za-z0-9_-]{16,}"), "cfte_" + MASK),            # per-site API keys
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), "sk-" + MASK),                 # OpenAI/OpenRouter-style keys
    (re.compile(r"\bhttps://discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_-]+"),
     "https://discord.com/api/webhooks/" + MASK),
]


def redact_text(text: Any) -> str:
    """`text` with credential-looking substrings masked. Safe on any input."""
    out = str(text)
    for pattern, repl in _PATTERNS:
        out = pattern.sub(repl, out)
    return out


def redact_headers(headers: Mapping[str, Any] | None) -> dict:
    """A copy of `headers` with every credential-bearing value masked."""
    return {k: (MASK if _SENSITIVE_KEY.search(str(k)) else v) for k, v in (headers or {}).items()}


def summarize(value: Any, limit: int = 160) -> str:
    """One short, redacted line for logging a tool result or payload instead of dumping it whole."""
    text = redact_text(" ".join(str(value).split()))
    return text if len(text) <= limit else f"{text[:limit]}… [{len(text)} chars]"
