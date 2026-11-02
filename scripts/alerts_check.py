"""Post operational alerts to Discord (OPS-01).

    python scripts/alerts_check.py              # print + post (if DISCORD_WEBHOOK_URL is set)
    python scripts/alerts_check.py --dry-run    # print only

Silent (and exit 0) when there is nothing to report, so a daily schedule does not add noise. The webhook URL is
a secret: it is read from the environment and never printed.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sdk.ops import collect_alerts, format_alerts  # noqa: E402


def run(dry_run: bool = False, post=None) -> dict:
    alerts = collect_alerts()
    text = format_alerts(alerts)
    posted = False
    hook = (os.environ.get("DISCORD_WEBHOOK_URL") or "").strip()
    if text and hook and not dry_run:
        if post is None:
            import requests

            def post(url, body):  # noqa: ANN001
                return requests.post(url, json={"content": body[:1900]}, timeout=15)
        try:
            resp = post(hook, text)
            posted = bool(getattr(resp, "ok", True))
        except Exception:  # noqa: BLE001 - never leak the URL via an exception message
            posted = False
    return {"alerts": alerts, "posted": posted}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ns = ap.parse_args()
    out = run(dry_run=ns.dry_run)
    print(format_alerts(out["alerts"]) or "no alerts")
    sys.exit(0)
