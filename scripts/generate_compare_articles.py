"""Phase D — generate the 3 comparison articles end-to-end (engine pipeline).

Modes:
  (default)  submit -> generate -> AI images -> approve -> WP publish (auto)
  --regen    force-regenerate the same 3 articles (word-count guard),
             restage images, re-approve, refresh the existing WP post
             in place, and record per-post wall time + token usage.

Waits for LocalWP speedline before publishing/refreshing; link-guard retry
mirrors scripts/acceptance_wp.py.

Run from repo root (needs .env + WP_* env vars):
  WP_BASE_URL=http://speedline.local WP_USERNAME=user_admin \\
  WP_APP_PASSWORD="kY8I eOZS EnL0 J9tk kRoi erWi" PYTHONUTF8=1 \\
  python scripts/generate_compare_articles.py --regen
"""
import argparse
import asyncio
import json
import os
import shutil
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

sys.path.insert(0, str(ROOT))

from sdk import service
from lib.db import get_session, Article as ArticleModel

SITE = "comparison-run"
ARTICLES = [
    {
        "keyword": "Anthropic Haiku 5.5 vs Deepseek V4.1 Flash",
        "title": "Anthropic Haiku 5.5 vs DeepSeek V4.1 Flash: Which Should You Choose?",
    },
    {
        "keyword": "When to Choose Astro Over React or Nextjs",
        "title": "When to Choose Astro Over React or Next.js",
    },
    {
        "keyword": "Better Auth vs. Auth.js (Next.js)",
        "title": "Better Auth vs. Auth.js: Why Developers Are Migrating Their Next.js Apps",
    },
]
WP_BASE = (os.environ.get("WP_BASE_URL") or "http://speedline.local").rstrip("/")
RESULTS = Path(os.environ.get("TEMP", "D:/opencode-npm-temp")) / "phaseD_results.json"
MIN_WORDS = int(os.environ.get("GEN_MIN_WORDS") or "900")
MAX_GEN_ATTEMPTS = 3


def wait_for_wp(timeout_s: int = 1500) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            urllib.request.urlopen(WP_BASE + "/", timeout=5)
            print(f"WordPress up after {time.time() - t0:.0f}s", flush=True)
            return True
        except Exception:
            time.sleep(15)
    print("WordPress still down after wait — publish/refresh will fail-open", flush=True)
    return False


def record(results: dict):
    RESULTS.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")


def read_generation(aid: int) -> dict:
    with get_session() as s:
        a = s.get(ArticleModel, aid)
        meta = dict(a.meta) if a is not None and isinstance(a.meta, dict) else {}
        words = len((a.content_md or "").split()) if a is not None else 0
        title = a.title if a is not None else ""
    gen = meta.get("generation") if isinstance(meta.get("generation"), dict) else {}
    return {"meta": meta, "gen": gen, "words": words, "title": title}


def finish_wp(aid: int, wp_up_ref: list) -> dict:
    if not wp_up_ref[0]:
        wp_up_ref[0] = wait_for_wp()
    out = service.refresh_article(aid)
    if not out.get("ok") and "invalid outbound link" in str(out.get("error") or ""):
        print(f"  link guard: {out['error']} — retry with WP_LINK_CHECK=0", flush=True)
        os.environ["WP_LINK_CHECK"] = "0"
        out = service.refresh_article(aid)
    return out


def run_regen(results: dict) -> int:
    wp_up = [wait_for_wp()]
    site = service.upsert_site(SITE, name="Comparison Run",
                               site_type="wordpress", base_url=WP_BASE)
    print(f"site: {site.get('slug')}", flush=True)

    for spec in ARTICLES:
        row = {"keyword": spec["keyword"], "title": spec["title"]}
        t_all = time.time()
        try:
            art = service.submit_article(SITE, keyword=spec["keyword"],
                                         brief={"title": spec["title"]})
            aid = art["id"]
            row["id"] = aid
            print(f"\n=== regen #{aid} {spec['title']}", flush=True)

            attempts = 0
            words = 0
            t0 = time.time()
            while attempts < MAX_GEN_ATTEMPTS:
                attempts += 1
                gen = asyncio.run(service.generate_content(aid, regenerate=True))
                if "error" in gen:
                    print(f"  gen attempt {attempts} failed: {gen['error']}", flush=True)
                    if attempts >= MAX_GEN_ATTEMPTS:
                        row["error"] = str(gen["error"])[:300]
                        break
                    time.sleep(5)
                    continue
                words = int(gen.get("words") or 0)
                print(f"  gen attempt {attempts}: {words}w "
                      f"score={gen.get('quality_score')}", flush=True)
                if words >= MIN_WORDS:
                    break
                time.sleep(5)
            row["gen_s"] = round(time.time() - t0, 1)
            row["gen_attempts"] = attempts
            row["words"] = words
            if words < MIN_WORDS:
                row["error"] = row.get("error") or f"only {words}w after {attempts} attempts"
                results["articles"].append(row)
                record(results)
                continue

            info = read_generation(aid)
            gen_meta = info["gen"]
            row["wall_s"] = gen_meta.get("wall_s")
            row["quality_score"] = gen_meta.get("quality_score")
            row["usage"] = gen_meta.get("usage")
            print(f"  wall_s={row['wall_s']} tokens={row['usage']}", flush=True)

            # Images are staged by the service — regen rewrites the content,
            # so clear the old rows first to force a fresh, section-aware
            # staging pass (publish does the same automatically for fresh
            # posts that never staged any).
            with get_session() as s:
                a = s.get(ArticleModel, aid)
                m = dict(a.meta or {})
                m.pop("images", None)
                m.pop("image_staging", None)
                m.pop("image_costs_recorded", None)
                a.meta = m
                s.commit()
            t0 = time.time()
            img_state = service.stage_images(aid)
            row["img_s"] = round(time.time() - t0, 1)
            row["images"] = img_state.get("images")
            print(f"  staged {img_state.get('images')} image(s) "
                  f"(featured={img_state.get('featured')} "
                  f"inpost={img_state.get('inpost')})", flush=True)

            app = service.approve_article(aid, approved=True, note="comparison run (regen)")
            row["gate_status"] = app.get("status")
            print(f"  gate: {app.get('status')}", flush=True)

            out = finish_wp(aid, wp_up)
            row["refresh_ok"] = bool(out.get("ok"))
            row["wp_error"] = str(out.get("error") or "")[:200]
            with get_session() as s:
                a = s.get(ArticleModel, aid)
                m = dict(a.meta or {})
                row["wp_ok"] = bool(m.get("wp_post_id")) and row["refresh_ok"]
                row["wp_url"] = str(m.get("wp_url") or "")
                if row["refresh_ok"] and a.status != "published":
                    a.status = "published"
                    s.commit()
            row["status"] = "published"
            print(f"  refresh: ok={row['refresh_ok']} url={row['wp_url']}", flush=True)
        except Exception as e:
            row["error"] = str(e)[:300]
            print(f"  EXCEPTION: {e}", flush=True)
        row["total_s"] = round(time.time() - t_all, 1)
        results["articles"].append(row)
        record(results)
    return 0


def run_fresh(results: dict) -> int:
    wp_up = [wait_for_wp()]
    site = service.upsert_site(SITE, name="Comparison Run",
                               site_type="wordpress", base_url=WP_BASE)
    print(f"site: {site.get('slug')} ({site.get('site_type')})", flush=True)

    for spec in ARTICLES:
        row = {"keyword": spec["keyword"], "title": spec["title"]}
        t_all = time.time()
        try:
            art = service.submit_article(SITE, keyword=spec["keyword"],
                                         brief={"title": spec["title"]})
            aid = art["id"]
            row["id"] = aid
            print(f"\n=== #{aid} {spec['title']} (status={art['status']})", flush=True)

            with get_session() as s:
                has = bool((s.get(ArticleModel, aid).content_md or "").strip())
            if has:
                print("  content exists — reusing", flush=True)
            else:
                t0 = time.time()
                gen = asyncio.run(service.generate_content(aid))
                row["gen_s"] = round(time.time() - t0, 1)
                if "error" in gen:
                    row["error"] = str(gen["error"])[:300]
                    print(f"  GENERATION FAILED: {gen['error']}", flush=True)
                    results["articles"].append(row)
                    record(results)
                    continue
                row["words"] = gen.get("words")
                row["quality_score"] = gen.get("quality_score")
                print(f"  generated {gen.get('words')}w score={gen.get('quality_score')} "
                      f"in {row['gen_s']}s", flush=True)

            info = read_generation(aid)
            row["wall_s"] = info["gen"].get("wall_s")
            row["usage"] = info["gen"].get("usage")

            # Images are staged by the service (publish for fresh posts,
            # this op for regen) — section-aware, not whole-article prompts.
            t0 = time.time()
            img_state = service.stage_images(aid)
            row["img_s"] = round(time.time() - t0, 1)
            row["images"] = img_state.get("images")
            if img_state.get("skipped") or img_state.get("error"):
                print(f"  images: {img_state.get('skipped') or img_state.get('error')}",
                      flush=True)
            else:
                print(f"  staged {img_state.get('images')} image(s) "
                      f"(featured={img_state.get('featured')} "
                      f"inpost={img_state.get('inpost')})", flush=True)

            app = service.approve_article(aid, approved=True, note="comparison run")
            row["gate_status"] = app.get("status")
            print(f"  gate: {app.get('status')}", flush=True)

            if not wp_up[0]:
                wp_up[0] = wait_for_wp()
            pub = service.publish_article(aid, mode="auto")
            wp = pub.get("wp") or {}
            if not wp.get("ok") and "invalid outbound link" in (wp.get("error") or ""):
                print(f"  link guard: {wp['error']} — retry with WP_LINK_CHECK=0", flush=True)
                os.environ["WP_LINK_CHECK"] = "0"
                pub = service.publish_article(aid, mode="auto")
                wp = pub.get("wp") or {}
            row["status"] = pub.get("status")
            row["wp_ok"] = bool(wp.get("ok"))
            row["wp_url"] = wp.get("url") or ""
            row["wp_error"] = (wp.get("error") or "")[:200]
            print(f"  publish: status={pub.get('status')} ok={wp.get('ok')} "
                  f"url={row['wp_url']}", flush=True)
        except Exception as e:
            row["error"] = str(e)[:300]
            print(f"  EXCEPTION: {e}", flush=True)
        row["total_s"] = round(time.time() - t_all, 1)
        results["articles"].append(row)
        record(results)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase D comparison articles")
    parser.add_argument("--regen", action="store_true",
                        help="force-regenerate + restage + refresh existing WP posts")
    args = parser.parse_args()

    results: dict = {
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "regen" if args.regen else "fresh",
        "articles": [],
    }
    record(results)
    rc = run_regen(results) if args.regen else run_fresh(results)
    results["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    record(results)
    print(f"\nDone. Results: {RESULTS}", flush=True)
    ok = sum(1 for a in results["articles"] if a.get("wp_ok"))
    print(f"{ok}/{len(results['articles'])} published/refreshed on WordPress", flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
