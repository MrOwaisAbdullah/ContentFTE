"""Encryption of site secrets at rest (SEC-14).

`Site.settings` is a JSON column that held the WordPress application password, the IndexNow / Bing keys, the
Discord webhook and the delivery-webhook secret in PLAINTEXT, so a database dump, a backup, a read replica or a
SQL console exposed every client's credentials. The API already never RETURNS them (lib/secrets_redact.py); this
module stops them being READABLE in the database:

    SECRETS_KEY=<fernet key>            encrypt on write, decrypt on use
    SECRETS_KEY=<new>,<old>             rotation: the first key encrypts, every listed key can decrypt

Generate a key with:  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Stored form is `enc:v1:<fernet token>`. A value without the prefix is legacy plaintext and is returned as-is, so
turning encryption on needs no flag day; `scripts/encrypt_site_secrets.py` converts the rows that already exist.
With no SECRETS_KEY nothing changes (plaintext, as before) - and in shared (multi-tenant) mode that is logged as
a warning, because that is exactly the deployment this protects.

The key must live OUTSIDE the database (environment / secret manager); a key stored next to the data protects
nothing.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Mapping, Optional

from lib.secrets_redact import SECRET_FIELDS

logger = logging.getLogger(__name__)

PREFIX = "enc:v1:"
_warned = False


class SecretError(RuntimeError):
    """A stored secret could not be decrypted (wrong/missing key). Never includes the value."""


def _keys() -> list:
    raw = (os.environ.get("SECRETS_KEY") or "").strip()
    return [k.strip() for k in raw.split(",") if k.strip()]


def _fernet():
    from cryptography.fernet import Fernet, MultiFernet
    keys = _keys()
    if not keys:
        return None
    return MultiFernet([Fernet(k.encode("ascii")) for k in keys])


def enabled() -> bool:
    return bool(_keys())


def is_encrypted(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


def encrypt(value: str) -> str:
    """`enc:v1:...` for a non-empty plaintext when a key is configured; otherwise the value unchanged."""
    if not isinstance(value, str) or not value or is_encrypted(value):
        return value
    f = _fernet()
    if f is None:
        _warn_once()
        return value
    return PREFIX + f.encrypt(value.encode("utf-8")).decode("ascii")


def decrypt(value: Any) -> Any:
    """Plaintext for an `enc:v1:` value; anything else (legacy plaintext, empty, non-string) is returned as-is."""
    if not is_encrypted(value):
        return value
    f = _fernet()
    if f is None:
        raise SecretError("a stored secret is encrypted but SECRETS_KEY is not set")
    try:
        return f.decrypt(value[len(PREFIX):].encode("ascii")).decode("utf-8")
    except Exception as exc:  # noqa: BLE001 - InvalidToken carries nothing useful and must not echo the value
        raise SecretError("a stored secret could not be decrypted (wrong or rotated-out SECRETS_KEY)") from exc


def _warn_once() -> None:
    global _warned
    if _warned:
        return
    _warned = True
    try:
        from lib.site_env import is_shared_mode
        if is_shared_mode():
            logger.warning("SECRETS_KEY is not set: client credentials are stored in PLAINTEXT in the database "
                           "(TENANCY_MODE=shared). Set SECRETS_KEY and run scripts/encrypt_site_secrets.py.")
    except Exception:  # noqa: BLE001
        pass


def _map_fields(settings: Optional[Mapping[str, Any]], fn) -> Dict[str, Any]:
    out: Dict[str, Any] = {k: (dict(v) if isinstance(v, Mapping) else v) for k, v in (settings or {}).items()}
    for group, key, _flag in SECRET_FIELDS:
        g = out.get(group)
        if isinstance(g, dict) and isinstance(g.get(key), str) and g[key]:
            g[key] = fn(g[key])
    return out


def encrypt_settings(settings: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """A copy of `settings` with every known secret field encrypted (idempotent)."""
    return _map_fields(settings, encrypt)


def decrypt_settings(settings: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """A copy of `settings` with every known secret field decrypted - for INTERNAL use, never for a response."""
    return _map_fields(settings, decrypt)


def secret_value(settings: Optional[Mapping[str, Any]], group: str, key: str) -> str:
    """One stored secret, decrypted, or "" (also "" when it cannot be decrypted - the caller then reports the
    integration as not configured instead of crashing a publish)."""
    g = (settings or {}).get(group)
    raw = g.get(key) if isinstance(g, Mapping) else ""
    try:
        return str(decrypt(raw) or "")
    except SecretError as exc:
        logger.error("%s.%s: %s", group, key, exc)
        return ""
