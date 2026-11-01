"""Keep per-site secrets out of API/MCP responses and out of lossy settings saves.

Plan refs: SEC-04 (`GET /sites` and MCP `list_sites` returned the raw
`Site.settings` JSON, including the WordPress application password, IndexNow/Bing
keys and the Discord webhook, to every caller and into LLM context) and CON-04
(`upsert_site` merged `settings` only at the top level, so saving a `wp` group
replaced the whole stored group).

Mirrors `console/lib/site-secrets.ts` on purpose: the console strips defensively
too, and `secrets_set` produced here is what it relies on once the values are gone.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Mapping, Optional, Tuple

# (group, key, flag). Flags are the stable names the console UI uses.
SECRET_FIELDS: Tuple[Tuple[str, str, str], ...] = (
    ("wp", "app_password", "wp_app_password"),
    ("indexing", "indexnow_key", "indexnow_key"),
    ("indexing", "bing_wmt_key", "bing_wmt_key"),
    ("notifications", "discord_webhook_url", "discord_webhook_url"),
    ("delivery", "webhook_url", "delivery_webhook_url"),
    ("delivery", "secret", "delivery_secret"),
)

# Safety net for secret-looking keys nobody has listed yet. Applied to non-empty
# *string* values only, so numeric config such as `max_tokens` survives.
_SECRET_KEY_RE = re.compile(
    r"(password|passwd|passphrase|secret|token|api[_-]?key|private[_-]?key|credential|webhook)|_key$",
    re.IGNORECASE,
)


def is_secret_key(key: str) -> bool:
    return bool(_SECRET_KEY_RE.search(str(key)))


def _non_empty_str(v: Any) -> bool:
    return isinstance(v, str) and v.strip() != ""


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items()
                if not (isinstance(v, str) and v != "" and is_secret_key(k))}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def redact_settings(settings: Optional[Mapping[str, Any]]) -> Tuple[Dict[str, Any], Dict[str, bool]]:
    """-> (settings with every secret removed, {flag: is_it_set}).

    The input is never mutated."""
    src = dict(settings) if isinstance(settings, Mapping) else {}
    flags: Dict[str, bool] = {}
    for group, key, flag in SECRET_FIELDS:
        g = src.get(group)
        flags[flag] = isinstance(g, Mapping) and _non_empty_str(g.get(key))
    return _scrub(src), flags


def merge_settings(current: Optional[Mapping[str, Any]],
                   incoming: Mapping[str, Any]) -> Dict[str, Any]:
    """Merge a settings patch into the stored settings.

    * A group (dict) is merged key-by-key into the stored group, so sending
      `{"wp": {"username": "x"}}` no longer discards the stored password.
    * A blank value for a secret-looking key means "keep the stored one".
    * `None` means "remove this key" (the explicit way to clear a secret).
    * Everything else overwrites. Inputs are not mutated.
    """
    out: Dict[str, Any] = dict(current) if isinstance(current, Mapping) else {}
    for k, v in (incoming or {}).items():
        if v is None:
            out.pop(k, None)
        elif isinstance(v, Mapping) and isinstance(out.get(k), Mapping):
            group = dict(out[k])
            for kk, vv in v.items():
                if vv is None:
                    group.pop(kk, None)
                elif vv == "" and is_secret_key(kk):
                    continue
                else:
                    group[kk] = vv
            out[k] = group
        elif v == "" and is_secret_key(k):
            continue
        else:
            out[k] = v
    return out
