"""Retry queued custom-site deliveries (ADP-04). Schedule it every few minutes (cron / Actions).

    python scripts/process_outbox.py

A delivery that failed on publish is stored in `delivery_outbox` and retried here with exponential backoff
(1m, 2m, 4m ... up to 6h, 8 attempts), always under the same X-CFTE-Delivery id. After the last attempt it is marked
`dead` and shows up in the alerts (`python scripts/alerts_check.py`). Prints counts only - never a URL or a secret.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.outbox import process_due  # noqa: E402

if __name__ == "__main__":
    print(process_due())
