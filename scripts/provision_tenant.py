"""Provision a ContentFTE tenant/instance (docs/spec-site2-postgres-frontend.md §4b).

Modes:
  shared   - create/update the Site + Brand DNA row in the CURRENT DATABASE_URL
             (the platform DB). The tenant process shares provider envs with
             the primary instance and sets TENANCY_MODE=shared. SaaS shape.
  isolated - print the checklist for a self-contained instance (own DB, own
             provider keys, own process). Site #2's shape.

Pure DB + stdout: no LLM, no network, no secrets printed.
"""
from __future__ import annotations

import argparse

_ISOLATED_CHECKLIST = """\
Isolated instance checklist (docs/spec-site2-postgres-frontend.md §4):
 1. Provision a new database (Neon project #2, or local sqlite for dev) and
    note its DATABASE_URL.
 2. Create provider accounts/keys for the free-tier share:
    Gemini, OpenRouter, Cloudflare Workers AI, Tavily (+ optional IndexNow/GSC).
 3. Copy env/site2.example (or .env.example) and fill:
      TENANCY_MODE=isolated
      DATABASE_URL=<this instance's DB>
      DEFAULT_SITE_SLUG=<its slug>
      SITE_BASE_URL=https://<its domain>
      SHEETS_ENABLED=0
      STORE_READ_SOURCE=postgres
      WP_BASE_URL / WP_USERNAME / WP_APP_PASSWORD   (wordpress target)
      GEMINI_API_KEY / OPENROUTER_API_KEY / CLOUDFLARE_* / TAVILY_API_KEY
      DISCORD_WEBHOOK_URL=<(new webhook in this tenant's server)>
      DISCORD_BOT_TOKEN=<(own bot app, or omit for console-only approvals)>
      DISCORD_APPROVAL_CHANNEL_IDS=<its approval channel(s), comma-separated>
 4. Copy this repo to the instance directory, run migrations/init:
      python -c "from lib.db import init_db; init_db()"
 5. Register the site:
      python scripts/provision_tenant.py --mode isolated --slug <slug> \\
          --name "<Name>" --site-type wordpress --site-url https://<domain>
    (prints only; the row is created on first pipeline run against this DB,
     or use --mode shared against this instance's DATABASE_URL to create it now)
 6. Follow docs/site-onboarding-flow.md §1 + §5 for the first article.
"""


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Provision a ContentFTE tenant (isolated instance or shared-DB tenant).")
    ap.add_argument("--mode", choices=("shared", "isolated"), default="isolated")
    ap.add_argument("--slug", default="", help="Site slug (required for --mode shared)")
    ap.add_argument("--name", default="", help="Display name (defaults to the slug)")
    ap.add_argument("--site-type", default="wordpress",
                    choices=("wordpress", "custom", "sanity"))
    ap.add_argument("--site-url", default="", help="Base URL, e.g. https://example.com")
    args = ap.parse_args()

    if args.mode == "isolated":
        print(_ISOLATED_CHECKLIST)
        if args.slug:
            print(f"(requested slug for step 5: {args.slug})")
        return

    # shared: create the tenant row in the CURRENT DATABASE_URL.
    if not args.slug:
        ap.error("--slug is required with --mode shared")
    from lib.db import get_session, init_db
    from lib.factory import provision_site

    init_db()
    session = get_session()
    try:
        result = provision_site(session, {
            "slug": args.slug,
            "name": args.name or args.slug,
            "site_type": args.site_type,
            "site_url": args.site_url,
        })
    finally:
        session.close()

    slug = result["slug"]
    print(f"Shared tenant provisioned: site_id={result['site_id']} slug={slug} "
          f"profile_version={result['profile_version']}")
    print("\nEnv overrides for this tenant's process (TENANCY_MODE=shared):")
    print(f"  TENANCY_MODE=shared")
    print(f"  DEFAULT_SITE_SLUG={slug}")
    if args.site_url:
        print(f"  SITE_BASE_URL={args.site_url.rstrip('/')}")
        print(f"  SEARCH_CONSOLE_SITE_URL={args.site_url.rstrip('/')}/")
    print("  SHEETS_ENABLED=0")
    print("  STORE_READ_SOURCE=postgres")
    print("  # WP_* if site_type=wordpress; DISCORD_WEBHOOK_URL /")
    print("  # DISCORD_APPROVAL_CHANNEL_IDS for this tenant's server;")
    print("  # provider keys may be SHARED with the primary instance.")


if __name__ == "__main__":
    main()
