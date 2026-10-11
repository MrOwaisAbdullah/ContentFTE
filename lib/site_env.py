"""Per-instance site identity + tenancy mode.

Spec: docs/spec-site2-postgres-frontend.md (deployment modes: isolated vs shared).

All defaults equal site #1 (owaisabdullah.dev) so existing behavior is
unchanged until an env var says otherwise. Import-time constants follow the
codebase style (module-level env snapshot); tenancy mode is a call-time read
so tests and long-lived processes can flip it per call site.
"""
import os

_DEFAULT_BASE = "https://owaisabdullah.dev"


def tenancy_mode() -> str:
    """`isolated` (own DB/process/env) or `shared` (platform DB, SaaS tenant)."""
    return (os.environ.get("TENANCY_MODE") or "isolated").strip().lower()


def is_shared_mode() -> bool:
    return tenancy_mode() == "shared"


# --- Site identity (Phase 1: de-hardcoded from 9 files; defaults = site #1) --
SITE_BASE_URL = (os.environ.get("SITE_BASE_URL") or _DEFAULT_BASE).rstrip("/")
SITE_HOST = SITE_BASE_URL.split("//", 1)[-1].split("/", 1)[0]
SITE_PREFIX = f"{SITE_BASE_URL}/blog/"
# Search Console properties include the trailing slash (site #1's property is
# exactly "https://owaisabdullah.dev/"). A domain property ("sc-domain:...")
# can be forced with SEARCH_CONSOLE_SITE_URL.
SITE_URL = f"{SITE_BASE_URL}/"
SEARCH_CONSOLE_SITE_URL = (os.environ.get("SEARCH_CONSOLE_SITE_URL") or SITE_URL).strip()
AUTHOR_PROFILE_API_URL = (
    os.environ.get("AUTHOR_PROFILE_API_URL") or f"{SITE_BASE_URL}/api/profile"
).strip()


def approval_channel_ids() -> list:
    """Discord approval channels this instance serves.

    DISCORD_APPROVAL_CHANNEL_IDS (comma-separated) wins; the legacy single
    DISCORD_APPROVAL_CHANNEL_ID still works. One bot token hosts ONE gateway
    process (Discord forbids two sessions per token), but that process may
    serve several channels -- e.g. one channel per tenant server after the
    shared bot is invited there.
    """
    raw = (os.environ.get("DISCORD_APPROVAL_CHANNEL_IDS", "").strip()
           or os.environ.get("DISCORD_APPROVAL_CHANNEL_ID", "").strip())
    ids = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            ids.append(int(part))
    return ids
