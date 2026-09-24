from __future__ import annotations

import asyncio
import importlib.util
import json
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

from lib.jev import call_jev  # noqa: E402
from lib.jev_helpers import check_duplicate_topic, find_duplicate_topic, gate_blog_topic  # noqa: E402

spec = importlib.util.spec_from_file_location("lt", ROOT / "scripts" / "live_jev_test.py")
lt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lt)

EXISTING = lt.EXISTING
CANDIDATES = lt.CANDIDATES


def score(rows, pred_key):
    ok = sum(1 for r in rows if r[pred_key] == r["truth_dup"])
    return ok, round(ok / len(rows), 3)


async def pairing() -> dict:
    sem = asyncio.Semaphore(4)

    async def one(i, cand, kind):
        async with sem:
            choice = await find_duplicate_topic(cand, EXISTING, threshold_conf=0.5)
            noul = await check_duplicate_topic(cand, EXISTING)
            return {
                "i": i,
                "kind": kind,
                "truth_dup": kind in ("exact_dup", "same_story"),
                "choice_raw": bool(choice["matched_topic"]),
                "choice_conf": choice["confidence"],
                "choice_fallback": choice["fallback"],
                "noul": noul["noul"],
                "noul_conf": noul["confidence"],
                "noul_fallback": noul["fallback"],
                "noul_0_6": noul["is_duplicate"],
            }

    rows = await asyncio.gather(*[one(i, c, k) for i, (c, k) in enumerate(CANDIDATES, 1)])

    for r in rows:
        r["choice_0_65"] = r["choice_raw"] and r["choice_conf"] >= 0.65
        r["choice_0_8"] = r["choice_raw"] and r["choice_conf"] >= 0.8

    res = {
        "n": len(rows),
        "choice_fallbacks": sum(1 for r in rows if r["choice_fallback"]),
        "noul_fallbacks": sum(1 for r in rows if r["noul_fallback"]),
        "noul_null_conf": sum(1 for r in rows if r["noul_conf"] == 0),
        "acc": {},
    }
    for key in ("choice_0_65", "choice_0_8", "noul_0_6"):
        ok, acc = score(rows, key)
        tp = sum(1 for r in rows if r[key] and r["truth_dup"])
        fp = sum(1 for r in rows if r[key] and not r["truth_dup"])
        fn = sum(1 for r in rows if not r[key] and r["truth_dup"])
        prec = tp / (tp + fp) if (tp + fp) else 1.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        res["acc"][key] = {"correct": ok, "accuracy": acc, "precision": round(prec, 3), "recall": round(rec, 3), "f1": round(f1, 3), "tp": tp, "fp": fp, "fn": fn}

    agreement = sum(1 for r in rows if r["choice_0_8"] == r["noul_0_6"])
    res["choice_vs_noul_agreement"] = f"{agreement}/{len(rows)}"
    res["rows"] = rows
    return res


async def forced_failures() -> dict:
    out = {}
    real_key = os.environ.get("OPENROUTER_API_KEY", "")

    os.environ["OPENROUTER_API_KEY"] = "invalid-test-key-forced-failure"
    g = await gate_blog_topic("test topic", "test brief")
    n = await check_duplicate_topic("test topic", EXISTING)
    c = await find_duplicate_topic("test topic", EXISTING)
    out["bad_key_401"] = {
        "gate_fallback": g["fallback"],
        "gate_needs_research": g["needs_research"],
        "gate_intent": g["intent"],
        "noul_fallback": n["fallback"],
        "noul_is_dup": n["is_duplicate"],
        "choice_fallback": c["fallback"],
        "choice_matched": c["matched_topic"],
    }

    os.environ["OPENROUTER_API_KEY"] = real_key

    try:
        await call_jev({"a": 1}, {"ok": {"type": "noul", "instructions": "Is it ok?"}}, model="typesafe/does-not-exist", max_retries=0)
        out["invalid_model_400"] = {"raised": False}
    except Exception as e:
        out["invalid_model_400"] = {"raised": True, "type": type(e).__name__, "status": getattr(e, "status", None), "message": str(e)[:160]}

    t0 = time.perf_counter()
    try:
        await call_jev({"a": 1}, {"ok": {"type": "noul", "instructions": "Is it ok?"}}, timeout_ms=1, max_retries=0)
        out["forced_timeout"] = {"raised": False, "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}
    except Exception as e:
        out["forced_timeout"] = {"raised": True, "type": type(e).__name__, "latency_ms": round((time.perf_counter() - t0) * 1000, 1), "message": str(e)[:120]}

    try:
        await call_jev({"a": 1}, {})
        out["empty_questions"] = {"raised": False}
    except Exception as e:
        out["empty_questions"] = {"raised": True, "type": type(e).__name__, "message": str(e)[:100]}

    try:
        await call_jev({"a": 1}, {"bad": {"type": "score", "instructions": "How good?", "criteria": ["only one"]}})
        out["score_one_criterion"] = {"raised": False}
    except Exception as e:
        out["score_one_criterion"] = {"raised": True, "type": type(e).__name__, "message": str(e)[:100]}

    return out


def bot_sync_path() -> dict:
    sys.path.insert(0, str(ROOT / "discord_bot"))
    import jev_helper

    out = {"timeout_ms_default": jev_helper.JEV_TIMEOUT_MS}
    cases = [
        ("pgvector vs Pinecone for content recommendation search", True),
        ("Supabase vs Firebase for indie SaaS backends", False),
        ("Dockerfile best practices for long-running Node bots", True),
    ]
    rows = []
    for cand, truth in cases:
        t0 = time.perf_counter()
        matched, raw, is_fallback = jev_helper.find_duplicate_topic(cand, EXISTING)
        ms = round((time.perf_counter() - t0) * 1000, 1)
        usage = (raw or {}).get("usage", {}) if raw else {}
        rows.append({
            "candidate": cand[:60],
            "truth_dup": truth,
            "matched": matched,
            "fallback": is_fallback,
            "correct": (matched is not None) == truth,
            "latency_ms": ms,
            "input_tokens": usage.get("input_tokens"),
            "cost": usage.get("cost"),
        })
    out["rows"] = rows
    out["correct"] = sum(1 for r in rows if r["correct"])
    out["n"] = len(rows)
    out["fallbacks"] = sum(1 for r in rows if r["fallback"])

    real_key = os.environ.get("OPENROUTER_API_KEY", "")
    os.environ["OPENROUTER_API_KEY"] = "invalid-test-key-bot"
    matched, raw, is_fallback = jev_helper.find_duplicate_topic("test topic", EXISTING)
    out["bad_key_fallback"] = {"matched": matched, "raw": raw, "fallback": is_fallback, "never_raised": True}
    os.environ["OPENROUTER_API_KEY"] = real_key
    return out


async def main() -> None:
    print("=== 1) PRODUCTION PAIRING: 20 candidates Choice + Noul ===")
    p = await pairing()
    for key, v in p["acc"].items():
        print(f"  {key:12s} acc={v['accuracy']:.2f} P={v['precision']:.2f} R={v['recall']:.2f} F1={v['f1']:.2f} tp={v['tp']} fp={v['fp']} fn={v['fn']}")
    print(f"  fallbacks choice={p['choice_fallbacks']} noul={p['noul_fallbacks']} | noul null-conf={p['noul_null_conf']}/{p['n']}")
    print(f"  choice(0.8) vs noul(0.6) agreement={p['choice_vs_noul_agreement']}")

    print("\n=== 2) FORCED FAILURES (must never raise / never block) ===")
    f = await forced_failures()
    for k, v in f.items():
        print(f"  {k}: {json.dumps(v, default=str)}")

    print("\n=== 3) DISCORD BOT requests PATH (sync, isolated Docker context) ===")
    b = bot_sync_path()
    for r in b["rows"]:
        print(f"  {r['candidate'][:48]:48s} matched={bool(r['matched'])} truth={r['truth_dup']} fallback={r['fallback']} {r['latency_ms']}ms cost={r['cost']}")
    print(f"  correct={b['correct']}/{b['n']} fallbacks={b['fallbacks']} timeout_default={b['timeout_ms_default']}ms")
    print(f"  bad_key -> {json.dumps(b['bad_key_fallback'])}")

    report = {"pairing": p, "forced_failures": f, "bot_sync": b}
    path = ROOT / "docs" / "jev-live-final-report.json"
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {path}")


if __name__ == "__main__":
    asyncio.run(main())
