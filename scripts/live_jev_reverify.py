# scripts/live_jev_reverify.py — re-verify fixed Noul gate + timeout diagnostic (LIVE)
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

sys.path.insert(0, str(ROOT))
from lib.jev import JEV_TIMEOUT_MS, call_jev  # noqa: E402
from lib.jev_helpers import check_duplicate_topic  # noqa: E402

spec = importlib.util.spec_from_file_location("lt", ROOT / "scripts" / "live_jev_test.py")
lt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lt)


async def main() -> None:
    print(f"JEV_TIMEOUT_MS at import: {JEV_TIMEOUT_MS}")
    for tmo in (1500, 5000):
        t0 = time.perf_counter()
        try:
            r = await call_jev(
                {"a": "ping"},
                {"ok": {"type": "noul", "instructions": "Is a ping ok?"}},
                timeout_ms=tmo,
                max_retries=0,
            )
            print(
                f"timeout_ms={tmo}: OK latency={(time.perf_counter() - t0) * 1000:.0f}ms "
                f"noul={r.answers['ok'].noul} conf={r.answers['ok'].confidence} cost={r.usage.cost}"
            )
        except Exception as e:
            print(f"timeout_ms={tmo}: FAIL latency={(time.perf_counter() - t0) * 1000:.0f}ms {type(e).__name__}: {e}")

    ok = 0
    for i, (cand, kind) in enumerate(lt.CANDIDATES, 1):
        r = await check_duplicate_topic(cand, lt.EXISTING)
        truth = kind in ("exact_dup", "same_story")
        hit = r["is_duplicate"] == truth
        ok += hit
        print(
            f"  [{i:02d}] {kind:11s} noul={r['noul']:.2f} conf={r['confidence']} "
            f"dup={r['is_duplicate']} truth={truth} {'OK' if hit else 'MISS'}"
        )
    print(f"fixed_noul_accuracy={ok}/20={ok / 20:.2f}")


if __name__ == "__main__":
    asyncio.run(main())
