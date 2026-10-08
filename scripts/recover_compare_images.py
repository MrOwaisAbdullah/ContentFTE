"""Recover the run-1 AI images for the comparison articles.

Phase D run 1 generated all 6 images (Cloudflare) but the staging step failed
on a local-path bug, and run 2 hit the daily neuron quota — so the images
live only as temp files in the OS temp dir. This script re-attaches them:

1. cluster today's temp images by >40s gaps -> 6 clusters
   (3 articles x featured/inpost, driver order = featured then inpost);
2. pick the winner per (article, slot) with the same VLM the pipeline
   ranks attempts by (image_vision.validate_thumbnail);
3. stage into Article.meta.images and refresh the WP post in place.

Run from repo root:  python scripts/recover_compare_images.py
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    import os
    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

sys.path.insert(0, str(ROOT))

from lib.db import Article as ArticleModel, get_session
from sdk import service

ARTICLES = [
    ("Anthropic Haiku 5.5 vs Deepseek V4.1 Flash", None),
    ("When to Choose Astro Over React or Nextjs", None),
    ("Better Auth vs. Auth.js (Next.js)", None),
]
IMG_DIR = Path("D:/opencode-npm-temp/contentfte_compare")
RESULTS = Path("D:/opencode-npm-temp/phaseD_results.json")
CLUSTER_GAP_S = 40
SINCE = time.mktime(time.strptime("2026-10-08 00:00", "%Y-%m-%d %H:%M"))


def find_candidates() -> list[Path]:
    pools = [Path(tempfile.gettempdir()), Path(r"C:\Users\K TECH\AppData\Local\Temp")]
    seen: set[str] = set()
    out: list[Path] = []
    for pool in pools:
        if not pool.is_dir():
            continue
        for p in sorted(pool.glob("tmp*"), key=lambda x: x.stat().st_mtime):
            if p.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
                continue
            if p.stat().st_mtime < SINCE:
                continue
            key = f"{p.name}:{p.stat().st_size}"
            if key in seen:
                continue
            seen.add(key)
            out.append(p)
    return out


def cluster(files: list[Path]) -> list[list[Path]]:
    groups: list[list[Path]] = []
    for f in files:
        if groups and f.stat().st_mtime - groups[-1][-1].stat().st_mtime <= CLUSTER_GAP_S:
            groups[-1].append(f)
        else:
            groups.append([f])
    return groups


def rank(v: dict) -> float:
    if not v:
        return -1.0
    if v.get("fallback"):
        return 0.001
    score = 0.0
    blog = v.get("matches_blog")
    style = v.get("matches_style")
    if isinstance(blog, (int, float)):
        score += float(blog)
    if isinstance(style, (int, float)):
        score += float(style)
    if v.get("passed"):
        score += 1000.0
    return score


def pick_winner(cands: list[Path], title: str, summary: str) -> tuple[Path, dict, float]:
    from lib import image_vision
    best, best_v = cands[-1], {}
    best_rank = -1.0
    for c in cands:
        try:
            v = image_vision.validate_thumbnail(str(c), title, summary) or {}
        except Exception as e:
            print(f"    validate {c.name} failed: {e}", flush=True)
            v = {}
        r = rank(v)
        print(f"    {c.name}: rank={r} passed={v.get('passed')} "
              f"blog={v.get('matches_blog')} style={v.get('matches_style')} "
              f"issues={'; '.join(str(x) for x in (v.get('issues') or [])[:2])}", flush=True)
        if r > best_rank:
            best, best_rank, best_v = c, r, v
    return best, best_v, best_rank


def main() -> int:
    import os
    files = find_candidates()
    print(f"candidates: {len(files)}", flush=True)
    groups = cluster(files)
    print(f"clusters: {len(groups)} -> " +
          " | ".join(f"{len(g)}f({g[0].stat().st_mtime:.0f})" for g in groups), flush=True)
    if len(groups) != 6:
        print(f"expected 6 clusters (3 articles x 2 slots), got {len(groups)} — aborting",
              flush=True)
        return 1

    with get_session() as s:
        arts = (s.query(ArticleModel)
                .filter(ArticleModel.site.has(slug="comparison-run"))
                .order_by(ArticleModel.id.asc())
                .all())
        pairs = []
        for a in arts:
            meta = dict(a.meta or {})
            keyword = str(meta.get("keyword") or "")
            summary = str(meta.get("summary") or "")
            idx = next((i for i, (k, _) in enumerate(ARTICLES) if k == keyword), None)
            if idx is None:
                print(f"article {a.id}: keyword not in plan: {keyword!r} — skipping",
                      flush=True)
                continue
            pairs.append((a.id, idx, a.title or "", summary))
    print("targets:", [(p[0], p[1]) for p in pairs], flush=True)
    if len(pairs) != 3:
        print(f"expected 3 target articles, got {len(pairs)} — aborting", flush=True)
        return 1

    staged: dict[int, list[dict]] = {}
    for t_idx, (aid, aidx, title, summary) in enumerate(pairs):
        print(f"\n=== article {aid} ({title[:60]})", flush=True)
        rows_meta = []
        for s_i, slot in enumerate(("featured", "inpost")):
            g = groups[aidx * 2 + s_i]
            print(f"  {slot}: {len(g)} candidate(s)", flush=True)
            winner, verdict, w_rank = pick_winner(g, title, summary)
            dest_dir = IMG_DIR
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / f"article{aid}_{slot}{winner.suffix.lower()}"
            shutil.copyfile(winner, dest)
            rows_meta.append({"slot": slot, "path": str(dest),
                              "alt": summary or title,
                              "qa": {"vlm_rank": w_rank,
                                     "passed": verdict.get("passed"),
                                     "matches_blog": verdict.get("matches_blog"),
                                     "matches_style": verdict.get("matches_style"),
                                     "recovered_from": winner.name}})
            print(f"  -> {winner.name} => {dest}", flush=True)
        staged[aid] = rows_meta

    for aid, rows_meta in staged.items():
        with get_session() as s:
            a = s.get(ArticleModel, aid)
            m = dict(a.meta or {})
            m["images"] = rows_meta
            a.meta = m
            s.commit()
        out = service.refresh_article(aid)
        print(f"article {aid}: refresh ok={out.get('ok')} {out.get('error') or ''}", flush=True)

    if RESULTS.is_file():
        data = json.loads(RESULTS.read_text(encoding="utf-8"))
        for row in data.get("articles", []):
            if row.get("id") in staged:
                row["img_recovered"] = True
                row["img_staged"] = [r["slot"] for r in staged[row["id"]]]
        RESULTS.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"updated {RESULTS}", flush=True)
    print("done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
