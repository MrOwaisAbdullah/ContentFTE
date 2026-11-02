"""Encrypt the secrets already stored in `sites.settings` (SEC-14).

    SECRETS_KEY=<fernet key> python scripts/encrypt_site_secrets.py            # do it
    SECRETS_KEY=<fernet key> python scripts/encrypt_site_secrets.py --dry-run  # count only

Idempotent: a value that is already `enc:v1:` is left alone, so it is safe to re-run. To move to a new key after a
rotation, set SECRETS_KEY=<new>,<old> and run with --reencrypt (every listed key can decrypt, the first encrypts).
Take a database backup first. Prints counts only - never a secret.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import secretbox  # noqa: E402
from lib.db import Site, get_session, init_db  # noqa: E402
from lib.secrets_redact import SECRET_FIELDS  # noqa: E402


def run(dry_run: bool = False, reencrypt: bool = False) -> dict:
    if not secretbox.enabled():
        return {"error": "SECRETS_KEY is not set - nothing to encrypt with"}
    init_db()
    s = get_session()
    changed_sites = changed_fields = 0
    try:
        for site in s.query(Site).all():
            settings = dict(site.settings or {})
            touched = 0
            for group, key, _flag in SECRET_FIELDS:
                g = settings.get(group)
                if not isinstance(g, dict) or not isinstance(g.get(key), str) or not g[key]:
                    continue
                value = g[key]
                if secretbox.is_encrypted(value):
                    if not reencrypt:
                        continue
                    value = secretbox.decrypt(value)           # raises SecretError if no listed key fits
                g = dict(g)
                g[key] = secretbox.encrypt(value)
                settings[group] = g
                touched += 1
            if touched:
                changed_sites += 1
                changed_fields += touched
                if not dry_run:
                    site.settings = settings                    # assign-before-commit (JSON column)
        if not dry_run:
            s.commit()
    finally:
        s.close()
    return {"sites_changed": changed_sites, "fields_encrypted": changed_fields, "dry_run": dry_run}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--reencrypt", action="store_true", help="decrypt with any listed key, re-encrypt with the first")
    ns = ap.parse_args()
    out = run(dry_run=ns.dry_run, reencrypt=ns.reencrypt)
    print(out)
    sys.exit(1 if "error" in out else 0)
