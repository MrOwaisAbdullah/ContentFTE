# scripts/live_jev_test.py — LIVE test (not mock): requires OPENROUTER_API_KEY in .env
# 1) Smoke: gate_blog_topic batched (Noul+Choice+Score) — latency, cost, confidence, probabilities
# 2) 20-candidate dedupe batch: Jev find_duplicate_topic (Choice) + check_duplicate_topic (Noul)
#    vs old DeepSeek chat path (same prompt as discord_bot/bot.py:_check_duplicate_topic)
# Threshold tuning capture: noul/confidence/probabilities/usage.cost/latencyMs
# Usage: .venv\Scripts\python.exe scripts\live_jev_test.py
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Load .env (same keys the pipeline uses) — do NOT print secrets
ROOT = Path(__file__).resolve().parents[1]
env_path = ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        if k and k not in os.environ:
            os.environ[k] = v.strip().strip('"').strip("'")

if not os.environ.get("OPENROUTER_API_KEY"):
    print("FATAL: OPENROUTER_API_KEY not set after .env load")
    sys.exit(2)

sys.path.insert(0, str(ROOT))

from lib.jev import JEV_MODEL, call_jev, jev_log_fields  # noqa: E402
from lib.jev_helpers import check_duplicate_topic, find_duplicate_topic, gate_blog_topic  # noqa: E402

# Existing topics fixture — realistic ContentFTE-style rows (synthetic, no sheet read)
EXISTING = [
    "Claude Code hooks for automated SEO content pipelines",
    "Building an AI blog agent with OpenRouter function tools",
    "Next.js 15 App Router SEO: metadata API deep dive",
    "pgvector vs Pinecone for content recommendation search",
    "TypeSafe Jev System One for LLM decision gating",
    "Docker multi-stage builds for Node.js blog agents",
    "Weekly keyword gap analysis with Google Search Console",
    "Repurposing blog posts into Twitter threads automatically",
    "Cloudflare R2 storage for AI-generated image assets",
    "Spec-driven development workflow for SaaS founders",
]

# 20 candidates: labeled ground truth for threshold tuning
# kind: exact_dup | same_story | same_broad | unrelated
CANDIDATES = [
    ("Claude Code hooks for automated SEO content pipelines (2026 update)", "exact_dup"),
    ("Using Claude Code hooks to schedule SEO blog generation", "same_story"),
    ("How I automated my entire content calendar with AI agents", "same_broad"),
    ("Building multi-agent blog research with OpenRouter tool calling", "same_broad"),
    ("OpenRouter function tools for blog agents: complete guide", "same_story"),
    ("Why LLM function calling fails without schema validation", "unrelated"),
    ("Next.js 15 metadata API for better blog SEO rankings", "exact_dup"),
    ("Next.js 15 View Transitions and their UX impact", "same_broad"),
    ("App Router streaming SSR performance benchmarks", "unrelated"),
    ("pgvector vs Pinecone for RAG on content archives", "same_story"),
    ("Choosing a vector database in 2026: practical guide", "same_broad"),
    ("Supabase vs Firebase for indie SaaS backends", "unrelated"),
    ("TypeSafe Jev decision model for production AI gates", "exact_dup"),
    ("Calibrated confidence scores for LLM output routing", "same_broad"),
    ("When to use a decision model instead of a bigger LLM", "same_story"),
    ("Dockerfile best practices for long-running Node bots", "same_broad"),
    ("Docker multi-stage builds to cut Node.js image size 60%", "exact_dup"),
    ("Kubernetes vs plain Docker Compose for small teams", "unrelated"),
    ("Keyword gap analysis playbook using Search Console API", "same_story"),
    ("Search Console API tutorial for rank tracking dashboards", "same_broad"),
]


async def smoke_gate() -> dict:
    print("\n=== 1) SMOKE: gate_blog_topic (Noul + Choice + Score batched) ===")
    t0 = time.perf_counter()
    g = await gate_blog_topic(
        topic="TypeSafe Jev System One for LLM decision gating in SEO pipelines",
        brief="Technical deep-dive on calibration, thresholds, and cost vs DeepSeek chat",
    )
    ms = (time.perf_counter() - t0) * 1000
    usage = g.get("usage") or {}
    out = {
        "needs_research": g["needs_research"],
        "intent": g["intent"],
        "trend": g["trend"],
        "fallback": g["fallback"],
        "latency_ms_roundtrip": round(ms, 1),
        "latency_ms_inner": g.get("latency_ms"),
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cost_usd": usage.get("cost"),
    }
    # Full probabilities/confidence via raw if present
    raw = g.get("raw")
    if raw is not None:
        out["answers_detail"] = jev_log_fields(raw, ms)
    print(json.dumps(out, indent=2, default=str))
    return out


async def deepseek_dup(candidate: str, existing: list[str]) -> str | None:
    """Old path: DeepSeek chat, exact prompt from discord_bot/bot.py:_check_duplicate_topic."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=os.environ["OPENROUTER_API_KEY"])
    prompt = (
        "Candidate topic:\n" + candidate + "\n\n"
        "Existing topics already queued, researched, or published (one per line):\n"
        + "\n".join(f"- {t}" for t in existing) + "\n\n"
        "Does the candidate cover essentially the SAME specific story/topic as any one of "
        "these -- not just the same general subject area (e.g. two different posts about "
        "\"AI agents\" broadly are NOT duplicates, but two posts about the same specific "
        "product's same specific release ARE)? Reply with ONLY the exact matching existing "
        "topic text if yes, or the single word NONE if no close match exists. No other text."
    )
    t0 = time.perf_counter()
    resp = await client.chat.completions.create(
        model="deepseek/deepseek-v4-flash-0731",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=200,
        temperature=0,
    )
    ms = (time.perf_counter() - t0) * 1000
    answer = (resp.choices[0].message.content or "").strip()
    usage = resp.usage
    cost = getattr(resp, "model_extra", None) or {}
    return {
        "matched": None if (not answer or answer.upper() == "NONE") else answer[:120],
        "latency_ms": round(ms, 1),
        "input_tokens": getattr(usage, "prompt_tokens", None),
        "raw": answer[:160],
    }


async def one_candidate(idx: int, cand: str, kind: str) -> dict:
    choice = await find_duplicate_topic(cand, EXISTING)
    noul = await check_duplicate_topic(cand, EXISTING)
    ds = await deepseek_dup(cand, EXISTING)
    row = {
        "i": idx,
        "kind": kind,
        "candidate": cand[:80],
        "jev_choice_matched": bool(choice["matched_topic"]),
        "jev_choice_topic": (choice["matched_topic"] or "")[:70],
        "jev_choice_conf": choice["confidence"],
        "jev_choice_fallback": choice["fallback"],
        "jev_noul_is_dup": noul["is_duplicate"],
        "jev_noul": noul["noul"],
        "jev_noul_conf": noul["confidence"],
        "jev_usage": noul.get("usage") or choice.get("usage"),
        "deepseek_matched": bool(ds["matched"]) if isinstance(ds, dict) else False,
        "deepseek_topic": (ds.get("matched") or "")[:70] if isinstance(ds, dict) else "",
        "deepseek_latency_ms": ds.get("latency_ms") if isinstance(ds, dict) else None,
        "deepseek_input_tokens": ds.get("input_tokens") if isinstance(ds, dict) else None,
    }
    # ground truth: exact_dup|same_story => should flag (duplicate advisory yes)
    row["truth_dup"] = kind in ("exact_dup", "same_story")
    row["jev_choice_tp"] = row["jev_choice_matched"] == row["truth_dup"]
    row["jev_noul_tp"] = row["jev_noul_is_dup"] == row["truth_dup"]
    row["deepseek_tp"] = row["deepseek_matched"] == row["truth_dup"] if isinstance(ds, dict) else None
    return row


async def batch_20() -> list[dict]:
    print(f"\n=== 2) BATCH: 20 candidates × (Jev Choice + Jev Noul + DeepSeek) — model={JEV_MODEL} ===")
    sem = asyncio.Semaphore(4)

    async def run(i, cand, kind):
        async with sem:
            r = await one_candidate(i, cand, kind)
            print(
                f"  [{i:02d}] {kind:11s} jev_choice={r['jev_choice_matched']} "
                f"(conf={r['jev_choice_conf']:.2f}) jev_noul={r['jev_noul']:.2f}/{r['jev_noul_conf']:.2f} "
                f"dup={r['jev_noul_is_dup']} deepseek={r['deepseek_matched']} "
                f"ok(choice)={r['jev_choice_tp']} ok(noul)={r['jev_noul_tp']} ok(ds)={r['deepseek_tp']}",
                flush=True,
            )
            return r

    rows = await asyncio.gather(*[run(i + 1, c, k) for i, (c, k) in enumerate(CANDIDATES)])
    return list(rows)


def summarize(rows: list[dict]) -> dict:
    n = len(rows)

    def rate(key):
        vals = [r[key] for r in rows if r.get(key) is not None]
        return round(sum(bool(v) for v in vals) / len(vals), 3) if vals else None

    # Cost totals (Jev only — DeepSeek cost not in usage by default)
    jev_costs = [(r.get("jev_usage") or {}).get("cost") or 0 for r in rows]
    jev_tokens = [(r.get("jev_usage") or {}).get("input_tokens") or 0 for r in rows]
    ds_lat = [r["deepseek_latency_ms"] for r in rows if r.get("deepseek_latency_ms")]
    noul_vals = [r["jev_noul"] for r in rows]
    conf_vals = [r["jev_choice_conf"] for r in rows]
    # Threshold sweep on noul (is_duplicate flag = noul>=t and conf>=0.65)
    sweep = {}
    for t in (0.6, 0.65, 0.7, 0.75, 0.8):
        tp = fp = fn = tn = 0
        for r in rows:
            pred = r["jev_noul"] >= t and (r.get("jev_noul_conf") or 0) >= 0.65
            if r["truth_dup"] and pred:
                tp += 1
            elif r["truth_dup"] and not pred:
                fn += 1
            elif not r["truth_dup"] and pred:
                fp += 1
            else:
                tn += 1
        prec = tp / (tp + fp) if (tp + fp) else 1.0
        rec = tp / (tp + fn) if (tp + fn) else 1.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0
        sweep[str(t)] = {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": round(prec, 3), "recall": round(rec, 3), "f1": round(f1, 3)}
    summary = {
        "n": n,
        "jev_choice_accuracy": rate("jev_choice_tp"),
        "jev_noul_accuracy": rate("jev_noul_tp"),
        "deepseek_accuracy": rate("deepseek_tp"),
        "jev_choice_fallbacks": sum(1 for r in rows if r.get("jev_choice_fallback")),
        "total_jev_input_tokens": sum(jev_tokens),
        "total_jev_cost_usd": round(sum(jev_costs), 6),
        "avg_jev_noul": round(sum(noul_vals) / n, 3),
        "avg_jev_choice_conf": round(sum(conf_vals) / n, 3),
        "avg_deepseek_latency_ms": round(sum(ds_lat) / len(ds_lat), 1) if ds_lat else None,
        "noul_threshold_sweep_vs_truth": sweep,
    }
    return summary


async def main() -> None:
    smoke = await smoke_gate()
    rows = await batch_20()
    summary = summarize(rows)
    report = {"smoke": smoke, "summary": summary, "rows": rows}
    out_path = ROOT / "docs" / "jev-live-test-report.json"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("\n=== SUMMARY ===")
    print(json.dumps(summary, indent=2))
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
