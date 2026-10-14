"""End-to-end check that blog_agent routes Gemini through gemini-free-router.

Run with the router up (`npm run router`) and GFR_BASE_URL set:
    GFR_BASE_URL=http://127.0.0.1:8787/v1 python scripts/test_router_integration.py

Exits 0 on success, 1 on failure. Prints what it verified.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    base = (os.environ.get("GFR_BASE_URL") or "").strip()
    if not base:
        print("FAIL: GFR_BASE_URL is not set (add it to .env)")
        return 1

    # 1. The client the runner builds must target the router, not Google.
    from blog_agent.custom_runner import FallbackAgentRunner

    runner = FallbackAgentRunner()
    client = runner.get_gemini_client()
    got_base = str(client.base_url).rstrip("/")
    if got_base != base.rstrip("/"):
        print(f"FAIL: client base_url={got_base}, expected {base}")
        return 1
    print(f"OK: get_gemini_client -> {got_base}")

    # 2. A real completion through the router (model auto-picks from fleet).
    import anyio

    async def probe() -> str:
        resp = await client.chat.completions.create(
            model="auto",
            messages=[{"role": "user", "content": "Reply with exactly: ROUTER_OK"}],
            temperature=0,
            max_tokens=20,
        )
        return (resp.choices[0].message.content or "").strip()

    text = anyio.run(probe)
    print(f"OK: completion through router -> {text[:80]!r}")
    if "ROUTER_OK" not in text:
        # Model may paraphrase; the fact we got ANY content back proves the
        # proxy path worked end to end (429/5xx would raise instead).
        print("WARN: expected ROUTER_OK token, but a non-empty reply still proves the path")
        if not text:
            print("FAIL: empty completion content")
            return 1

    # 3. Router admin must report the free plan and the merged fleet.
    import urllib.request

    with urllib.request.urlopen("http://127.0.0.1:8787/admin", timeout=5) as r:
        admin = __import__("json").loads(r.read())
    plan = admin.get("plan")
    fleet = admin.get("fleet") or []
    fleet_len = len(fleet)
    print(f"OK: /admin plan={plan} fleet_mode={admin.get('fleet_mode')} fleet={fleet_len} models")
    if plan != "free":
        print(f"FAIL: expected plan=free (got {plan})")
        return 1
    # Built-in 11 + gemini-flash-latest appended = 12 (gemma-4-* are in
    # `disabled:` — Google 500s them on this account, see router.yaml).
    if fleet_len < 12:
        print(f"FAIL: expected >=12 fleet models after merge (got {fleet_len})")
        return 1
    names = {m.get("model") for m in fleet}
    if "gemini-flash-latest" not in names:
        print("FAIL: gemini-flash-latest missing from merged fleet")
        return 1
    print("OK: appended model present (gemini-flash-latest); gemma-4-* disabled")
    if {"gemma-4-26b-a4b-it", "gemma-4-31b-it"} & names:
        print("FAIL: disabled gemma models still in fleet")
        return 1

    print("\nALL CHECKS PASSED -- blog agent is talking Gemini via gemini-free-router")
    return 0


if __name__ == "__main__":
    sys.exit(main())
