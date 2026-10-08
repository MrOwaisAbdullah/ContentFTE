"""Compare old (ContentSpark sheet) vs new (ContentFTE engine) articles.

Usage (repo root):
  python scripts/compare_results.py                  # metrics + judge + report
  python scripts/compare_results.py --metrics-only   # skip LLM judge
  python scripts/compare_results.py --report-only    # rebuild report from cache
  python scripts/compare_results.py --no-fetch       # skip live-URL checks

Outputs: docs/engine-vs-baseline-report.md
Cache:   <temp>/compare_cache.json (judge results + metrics, reruns are cheap)
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

import requests

ENGINE = os.environ.get("COMPARE_ENGINE_URL", "http://127.0.0.1:8123")
SHEET = "ContentSpark"
GENERATED = "generated_posts"
PUBLISHED = "published_posts"
CLAIMS = "claims_audit"
CACHE_PATH = Path(os.environ.get("COMPARE_CACHE", r"D:\opencode-npm-temp\compare_cache.json"))
REPORT_PATH = ROOT / "docs" / "engine-vs-baseline-report.md"

JUDGE_MODELS = [m.strip() for m in os.environ.get(
    "COMPARE_JUDGE_MODELS",
    "gemini-3.5-flash,gemini-3.6-flash,gemini-flash-latest,gemini-3.5-flash-lite",
).split(",") if m.strip()]
JUDGE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"

WEIGHTS = {"facts": 30, "style": 20, "seo": 20, "tone": 10, "structure": 10, "images": 5, "length": 5}

AI_PATTERNS = [
    r"\bdelve[sd]?\b", r"\bdelving\b", r"\bin today's (fast-paced|digital) [a-z]+\b",
    r"\bit'?s important to (note|understand|remember)\b", r"\bgame-?changer\b",
    r"\bunlock(?:ing|s)? (?:the |your )?(?:power|potential)\b", r"\bunleash\b",
    r"\bseamless(?:ly)?\b", r"\bleverage(?:s|d)?\b", r"\bnavigat(?:e|ing) (?:the |complex)\b",
    r"\b(?:the |a )?(?:ever-evolving|dynamic) landscape\b", r"\brealm of\b",
    r"\btestament to\b", r"\bfurthermore\b", r"\bmoreover\b", r"\bcomprehensive (?:guide|overview)\b",
    r"\bin conclusion\b", r"\bto sum up\b", r"\bat the end of the day\b",
    r"\bwhether you'?re (?:a|an) .{1,40} or (?:a|an) .{1,30}\b", r"\brich tapestry\b",
    r"\bembark(?:ing)? on\b", r"\bcraft(?:ing|ed)? (?:compelling|captivating)\b",
]
CONCLUSION_RE = re.compile(r"(conclusion|final (thoughts|verdict)|key takeaways?|summary|bottom line|verdict|closing thoughts)", re.I)
JUDGE_RUBRIC = """You are a strict content-quality auditor. Score ONLY the article below.
Return STRICT JSON, no prose, exactly this shape:
{"facts":{"score":<1-5>,"issues":"<short>"},"tone":{"score":<1-5>,"issues":"<short>"},"style":{"score":<1-5>,"issues":"<short>"}}
Rubric:
- facts: 5 = every claim specific, plausible, internally consistent, no hallucination markers, numbers caveated; 3 = mostly sound, some vague/unsourced claims; 1 = obvious errors or fabricated specifics.
- tone: 5 = confident, direct, expert-to-peer, no hype/emoji/cliché; 3 = occasionally salesy or generic; 1 = hype, fluff, or inconsistent voice.
- style: 5 = tight prose, varied sentence length, scannable, no AI clichés (delve/leverage/game-changer/rule-of-three), concrete examples; 3 = readable but generic in places; 1 = AI-slop patterns, repetitive, bloated.
Judge the writing itself; do not reward length or formatting. Be harsh and calibrated."""


# ---------- shared metrics ----------

def strip_md(md: str) -> str:
    md = re.sub(r"```.*?```", " ", md, flags=re.S)
    md = re.sub(r"!\[([^\]]*)\]\([^)]*\)", " ", md)
    md = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", md)
    md = re.sub(r"^[#>*\-|]+\s*", "", md, flags=re.M)
    md = re.sub(r"[*_`~]", "", md)
    return md


def count_syllables(word: str) -> int:
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return 0
    groups = re.findall(r"[aeiouy]+", w)
    n = len(groups)
    if w.endswith("e") and n > 1 and not w.endswith(("le", "ee", "ye")):
        n -= 1
    return max(1, n)


def readability(text: str):
    text = strip_md(text)
    sentences = [s for s in re.split(r"[.!?]+[\s)]", text) if len(s.split()) >= 3]
    words = text.split()
    if not sentences or len(words) < 20:
        return None, None
    syll = sum(count_syllables(w) for w in words)
    W, S = len(words), len(sentences)
    fre = 206.835 - 1.015 * (W / S) - 84.6 * (syll / W)
    fkgl = 0.39 * (W / S) + 11.8 * (syll / W) - 15.59
    return round(fre, 1), round(fkgl, 1)


def compute_metrics(a: dict) -> dict:
    md = a.get("markdown") or ""
    title = a.get("title") or ""
    meta = a.get("excerpt") or ""
    keyword = (a.get("keyword") or title).lower()
    kw_tokens = [t for t in re.findall(r"[a-z0-9]+", keyword) if len(t) > 3][:6]
    plain = strip_md(md)
    words = plain.split()
    n_words = len(words)
    headings = re.findall(r"^(#{2,4})\s+(.+)$", md, flags=re.M)
    h2 = [h for lvl, h in headings if lvl == "##"]
    h3 = [h for lvl, h in headings if lvl == "###"]
    levels = [len(lvl) for lvl, _ in headings]
    hierarchy_ok = levels == sorted(levels) and (not levels or levels[0] == 2)
    body_before_h2 = md.split("##")[0] if "##" in md else ""
    intro_words = len(strip_md(body_before_h2).split())
    first_h2_texts = " ".join(h2[:1] or [""])
    has_conclusion = bool(CONCLUSION_RE.search(h2[-1] if h2 else "")) or bool(CONCLUSION_RE.search(" ".join(h2[-3:])))
    faqs = a.get("faqs") or []
    if isinstance(faqs, str):
        try:
            faqs = json.loads(faqs)
        except Exception:
            faqs = []
    ext_links = re.findall(r"\]\((https?://[^)]+)\)", md)
    int_links = re.findall(r"\]\((/(?!/)[^)]*|#[^)]*|[a-z0-9-]+(?:/[a-z0-9-]+)+)\)", md)
    imgs = re.findall(r"!\[([^\]]*)\]\(([^)]+)\)", md)
    html_imgs = re.findall(r"<img[^>]*>", a.get("html") or "", flags=re.I)
    if not imgs and html_imgs:
        alts = [re.search(r'alt="([^"]*)"', t, flags=re.I) for t in html_imgs]
        imgs = [((m.group(1) if m else ""), "html") for m in alts]
    img_alts = sum(1 for alt, _ in imgs if alt.strip())
    ai_hits = sum(len(re.findall(p, plain, flags=re.I)) for p in AI_PATTERNS)
    sentences = [s for s in re.split(r"[.!?]+[\s)]", plain) if len(s.split()) >= 3]
    passive = sum(len(re.findall(r"\b(?:is|are|was|were|been|being)\s+(?:\w+ly\s+)?\w+ed\b", s)) for s in sentences)
    fre, fkgl = readability(md)
    paras = [p for p in re.split(r"\n\s*\n", md) if p.strip() and not p.strip().startswith("#")]
    para_words = [len(strip_md(p).split()) for p in paras]
    kw_in_title = any(t in title.lower() for t in kw_tokens) if kw_tokens else None
    first100 = " ".join(words[:100]).lower()
    kw_in_first100 = (sum(1 for t in kw_tokens if t in first100) / len(kw_tokens)) if kw_tokens else None
    kw_in_h2 = any(any(t in h.lower() for t in kw_tokens) for h in h2) if kw_tokens else None

    seo_items = {
        "meta_len_70_165": 70 <= len(meta) <= 165,
        "title_len_30_75": 30 <= len(title) <= 75,
        "kw_in_title": bool(kw_in_title),
        "kw_in_first100": kw_in_first100 is not None and kw_in_first100 >= 0.5,
        "kw_in_h2": bool(kw_in_h2),
        "h2_ge_4": len(h2) >= 4,
        "has_faq": len(faqs) >= 3,
        "ext_links_ge_2": len(ext_links) >= 2,
        "has_image": len(imgs) >= 1,
        "has_conclusion": has_conclusion,
    }
    seo_score = round(100 * sum(seo_items.values()) / len(seo_items))
    struct_items = {
        "hierarchy_ok": hierarchy_ok,
        "intro_le_150": intro_words <= 150,
        "has_conclusion": has_conclusion,
        "has_list_or_table": bool(re.search(r"^\s*[-*]\s|\|[\s-]*\|", md, flags=re.M)),
        "tldr_blockquote": bool(re.search(r"^>\s", md, flags=re.M)),
        "para_avg_le_120": bool(para_words) and mean(para_words) <= 120,
        "h2_ge_4": len(h2) >= 4,
    }
    struct_score = round(100 * sum(struct_items.values()) / len(struct_items))
    if 1200 <= n_words <= 2600:
        length_score = 100
    elif 900 <= n_words < 1200 or 2600 < n_words <= 3500:
        length_score = 80
    elif 600 <= n_words < 900 or 3500 < n_words <= 4500:
        length_score = 60
    elif n_words >= 400:
        length_score = 40
    else:
        length_score = 20
    img_ok = len(imgs) >= 1
    img_alt_ok = (img_alts / len(imgs)) >= 0.8 if imgs else False
    image_score = (40 if img_ok else 0) + (40 if img_alt_ok else 0) + (20 if len(imgs) >= 2 else 0)
    if not img_ok and a.get("image_source"):
        image_score = 20

    return {
        "words": n_words,
        "h2": len(h2), "h3": len(h3),
        "intro_words": intro_words,
        "has_conclusion": has_conclusion,
        "faq_count": len(faqs),
        "ext_links": len(ext_links), "int_links": len(int_links),
        "images": len(imgs), "image_alt_pct": round(100 * img_alts / len(imgs)) if imgs else 0,
        "ai_hits_per_1k": round(1000 * ai_hits / max(n_words, 1), 2),
        "passive_per_100": round(100 * passive / max(len(sentences), 1), 2),
        "flesch": fre, "fkgl": fkgl,
        "title_chars": len(title), "meta_chars": len(meta),
        "para_avg_words": round(mean(para_words)) if para_words else 0,
        "seo_score": seo_score, "seo_items": seo_items,
        "structure_score": struct_score, "struct_items": struct_items,
        "length_score": length_score, "image_score": image_score,
        "kw_in_title": kw_in_title, "kw_in_first100": round(kw_in_first100, 2) if kw_in_first100 is not None else None,
    }


# ---------- fetchers ----------

def fetch_old(limit: int) -> list[dict]:
    import gspread
    creds = json.loads(os.environ["GOOGLE_CREDENTIALS"])
    gc = gspread.service_account_from_dict(creds)
    sh = gc.open(SHEET)
    rows = sh.worksheet(GENERATED).get_all_values()
    hdr = rows[0]
    idx = {h: i for i, h in enumerate(hdr)}
    arts = []
    for r in rows[1:]:
        if not any(c.strip() for c in r):
            continue
        get = lambda h: (r[idx[h]] if h in idx and idx[h] < len(r) else "")
        if get("Published").strip().lower() != "yes":
            continue
        arts.append({
            "title": get("Title"),
            "markdown": get("Generated Content"),
            "faqs": get("FAQs"),
            "excerpt": get("Summary"),
            "sheet_score": get("Quality Score"),
            "created_at": get("Created At"),
            "image_source": get("Image Source"),
            "keyword": get("Title"),
            "html": "",
        })
    arts.sort(key=lambda a: a["created_at"])
    old = arts[-limit:]

    try:
        urls = sh.worksheet(PUBLISHED).get_all_values()
        uh = {h: i for i, h in enumerate(urls[0])}
        def slugify(s):
            return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
        url_by_slug = {}
        for r in urls[1:]:
            if len(r) > uh.get("Post URL", 0) and r[uh["Post URL"]]:
                url_by_slug[r[uh["Post URL"]].rstrip("/").split("/")[-1]] = r[uh["Post URL"]]
        for a in old:
            a["url"] = url_by_slug.get(slugify(a["title"]), "")
    except Exception:
        for a in old:
            a["url"] = ""
    return old


def fetch_new(site: str = "", limit: int = 3) -> list[dict]:
    qs = f"?limit=50" + (f"&site_slug={site}" if site else "")
    lst = requests.get(f"{ENGINE}/sdk/v1/articles{qs}", timeout=15).json()
    cands = [x for x in lst.get("articles", []) if x.get("status") in ("published", "approved")]
    cands.sort(key=lambda x: x.get("created_at") or "")
    picked = cands[-limit:]
    out = []
    for p in reversed(picked):
        c = requests.get(f"{ENGINE}/sdk/v1/articles/{p['id']}/content", timeout=20).json()
        if "error" in c and "html" not in c:
            print(f"  ! content fetch failed for {p['id']}: {c}")
            continue
        meta = c.get("meta") or {}
        out.append({
            "title": c.get("title") or p["title"],
            "markdown": c.get("markdown") or "",
            "html": c.get("html") or "",
            "faqs": meta.get("faqs") or [],
            "excerpt": c.get("excerpt") or "",
            "sheet_score": (c.get("scores") or {}).get("overall", ""),
            "created_at": p.get("created_at") or "",
            "image_source": "engine" if "<img" in (c.get("html") or "") else "",
            "image_source_generated": bool(re.search(r"<img[^>]+src=\"[^\"]*(?:generate|ai|picsum|images/)", c.get("html") or "", re.I)) or bool(meta.get("images")),
            "url": c.get("url") or "",
            "cost_usd": c.get("cost_usd") or 0,
            "status": c.get("status") or p.get("status"),
            "engine_scores": c.get("scores") or {},
            "id": p["id"],
            "keyword": p.get("keyword") or c.get("title") or "",
        })
    return out


def fetch_checks(urls: list[str]) -> dict:
    out = {}
    for u in urls:
        if not u:
            continue
        try:
            r = requests.get(u, timeout=12, headers={"User-Agent": "Mozilla/5.0 (content-audit)"})
            h = r.text
            ld_types = sorted(set(re.findall(r'"@type"\s*:\s*"([A-Za-z]+)"', h)))
            img_tags = re.findall(r"<img[^>]*>", h, re.I)
            img_alts = [m.group(1) if m else "" for m in
                        (re.search(r'alt="([^"]*)"', t, flags=re.I) for t in img_tags)]
            title = re.search(r"<title>(.*?)</title>", h, re.S | re.I)
            desc = re.search(r'<meta[^>]+name="description"[^>]+content="([^"]*)"', h, re.I) or \
                   re.search(r'<meta[^>]+content="([^"]*)"[^>]+name="description"', h, re.I)
            out[u] = {
                "status": r.status_code,
                "title_len": len(title.group(1).strip()) if title else 0,
                "meta_desc": bool(desc),
                "meta_len": len(desc.group(1)) if desc else 0,
                "ld_types": [t for t in ld_types if t in ("Article", "FAQPage", "BlogPosting", "BreadcrumbList", "WebPage", "HowTo", "NewsArticle", "SocialMediaPosting")],
                "og": bool(re.search(r'property="og:title"', h, re.I)),
                "h1_count": len(re.findall(r"<h1[^>]*>", h, re.I)),
                "img_count": len(img_tags),
                "img_alt_pct": round(100 * sum(1 for a in img_alts if a.strip()) / len(img_tags)) if img_tags else 0,
            }
        except Exception as e:
            out[u] = {"error": str(e)[:80]}
    return out


# ---------- ops (time + tokens) ----------

PHASED_RESULTS = Path(os.environ.get("COMPARE_PHASED",
                                     r"D:\opencode-npm-temp\phaseD_results.json"))


def _ts(s: str):
    from datetime import datetime
    s = (s or "").strip().replace(" UTC", "").strip()
    for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s, f)
        except ValueError:
            continue
    return None


def fetch_old_ops() -> dict:
    """Per-old-article LLM time + call count from model_usage_log, bucketed
    into (previous Created At, Created At] windows; image time from
    image_logs generate rows whose subject matches the title.
    Old token usage was never logged (sheet has no token columns)."""
    import gspread
    creds = json.loads(os.environ["GOOGLE_CREDENTIALS"])
    gc = gspread.service_account_from_dict(creds)
    sh = gc.open(SHEET)

    gen = sh.worksheet(GENERATED).get_all_values()
    gh = {h: i for i, h in enumerate(gen[0])}
    created = []
    for r in gen[1:]:
        if len(r) <= gh.get("Published", 0):
            continue
        if r[gh["Published"]].strip().lower() != "yes":
            continue
        t = _ts(r[gh["Created At"]] if gh.get("Created At", 0) < len(r) else "")
        if t:
            created.append((t, r[gh["Title"]] if gh.get("Title", 0) < len(r) else ""))
    created.sort(key=lambda x: x[0])

    usage = sh.worksheet("model_usage_log").get_all_values()
    uh = {h: i for i, h in enumerate(usage[0])}
    marks = [t for t, _ in created]
    buckets = [{"llm_s": 0.0, "calls": 0} for _ in created]
    for r in usage[1:]:
        if len(r) <= max(uh.get("Timestamp", 0), uh.get("Latency (s)", 0)):
            continue
        ts = _ts(r[uh["Timestamp"]])
        if not ts:
            continue
        lo, hi = 0, len(marks) - 1
        idx = -1
        for i, m in enumerate(marks):
            if ts <= m:
                idx = i
                break
        if idx < 0:
            continue
        if idx > 0 and ts <= marks[idx - 1]:
            continue
        try:
            lat = float(r[uh["Latency (s)"]] or 0)
        except ValueError:
            continue
        buckets[idx]["llm_s"] += lat
        buckets[idx]["calls"] += 1

    imgs = sh.worksheet("image_logs").get_all_values()
    ih = {h: i for i, h in enumerate(imgs[0])}
    img_rows = []
    for r in imgs[1:]:
        if len(r) <= max(ih.get("Timestamp", 0), ih.get("Latency (s)", 0)):
            continue
        if (r[ih["Stage"]] if ih.get("Stage", 0) < len(r) else "") != "generate":
            continue
        ts = _ts(r[ih["Timestamp"]])
        try:
            lat = float(r[ih["Latency (s)"]] or 0)
        except ValueError:
            continue
        if ts:
            img_rows.append((ts, r[ih["Subject"]] if ih.get("Subject", 0) < len(r) else "", lat))

    def norm(s):
        return re.sub(r"[^a-z0-9]+", "", (s or "").lower())

    out = {}
    for i, (t, title) in enumerate(created):
        nt = norm(title)
        img_s = sum(lat for _, subj, lat in img_rows
                    if nt and (norm(subj) in nt or nt in norm(subj)))
        out[title] = {"llm_s": round(buckets[i]["llm_s"], 1),
                      "calls": buckets[i]["calls"],
                      "img_s": round(img_s, 1) if img_s else None}
    return out


def new_ops_rows() -> list[dict]:
    if not PHASED_RESULTS.is_file():
        return []
    data = json.loads(PHASED_RESULTS.read_text(encoding="utf-8"))
    rows = []
    for a in data.get("articles", []):
        u = a.get("usage") or {}
        rows.append({
            "title": a.get("title", ""),
            "words": a.get("words"),
            "attempts": a.get("gen_attempts", 1 if a.get("gen_s") else None),
            "gen_s": a.get("gen_s") or a.get("wall_s"),
            "wall_s": a.get("wall_s"),
            "img_s": a.get("img_s"),
            "total_s": a.get("total_s"),
            "input_tokens": u.get("input_tokens"),
            "output_tokens": u.get("output_tokens"),
            "total_tokens": u.get("total_tokens"),
            "img_recovered": a.get("img_recovered"),
        })
    return rows


def ops_lines(old_rows, new_rows) -> list[str]:
    L = []
    L.append("## Ops: local time & tokens per post\n")
    new_ops = new_ops_rows()
    if new_ops:
        L.append("| New article | Words | Gen attempts | Gen wall (s) | Image (s) | Total (s) | In tokens | Out tokens | Total tokens |")
        L.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
        for r in new_ops:
            L.append(f"| {r['title'][:58]} | {r['words'] or '-'} | {r['attempts'] or '-'} | "
                     f"{fmt(r['gen_s'])} | {fmt(r['img_s'])} | {fmt(r['total_s'])} | "
                     f"{fmt(r['input_tokens'], 0)} | {fmt(r['output_tokens'], 0)} | "
                     f"{fmt(r['total_tokens'], 0)} |")
        g = [r for r in new_ops if r.get("gen_s")]
        tk = [r["total_tokens"] for r in new_ops if r.get("total_tokens")]
        tot = [r["total_s"] for r in new_ops if r.get("total_s")]
        L.append(f"| **avg / total** | | | **{fmt(mean([r['gen_s'] for r in g]) if g else None)}** | "
                 f"**{fmt(mean([r['img_s'] for r in new_ops if r.get('img_s')]))}** | "
                 f"**{fmt(mean(tot) if tot else None)}** | | | "
                 f"**{int(sum(tk)) if tk else '-'}** |")
        L.append("")

    try:
        old_ops = fetch_old_ops()
    except Exception as e:
        old_ops = {}
        L.append(f"*(old ops fetch failed: {str(e)[:80]})*\n")
    if old_ops:
        matched = [old_ops.get(r["meta"].get("title", ""), {}) for r in old_rows]
        matched = [m for m in matched if m.get("calls") is not None]
        if matched:
            llm = [m["llm_s"] for m in matched]
            calls = [m["calls"] for m in matched if m["calls"]]
            imgs = [m["img_s"] for m in matched if m.get("img_s")]
            L.append("Old baseline (from `model_usage_log` / `image_logs`, bucketed by `Created At` windows):\n")
            L.append(f"- LLM time per post (sum of call latencies): **avg {fmt(mean(llm))}s**, "
                     f"median {fmt(median(llm))}s, range {fmt(min(llm))}–{fmt(max(llm))}s")
            if calls:
                L.append(f"- LLM calls per post: **avg {fmt(mean(calls))}** (bucketed rows incl. retries/errors)")
            if imgs:
                L.append(f"- Image generate time per post: **avg {fmt(mean(imgs))}s** ({len(imgs)}/{len(matched)} matched)")
            L.append("- Tokens: **not logged** — the old pipeline's `model_usage_log` has no token columns (latency only)")
            L.append("")
    L.append("Notes:\n")
    L.append("- New *gen wall* = measured wall clock around `generate_content` (driver t0); *Total* = submit→publish/refresh wall clock from `phaseD_results.json`.")
    L.append("- New token usage = sum over the final generation attempt's model responses (`article.meta.generation.usage`); retries of a failed attempt are not merged into that number.")
    L.append("- The engine's `cost_ledger` currently persists $0.00 totals (cost wiring gap, tracked in TASKS) — tokens above come from the Agents SDK response usage, not the ledger.")
    L.append("- Old-side LLM time is a latency-sum approximation: rows are bucketed into Created-At windows, so tool/network gaps between calls are excluded and idle time between posts can be misattributed.")
    L.append("- Image staging: run 1 produced all 6 AI images but the driver dropped them on a local-path bug; run 2 hit Cloudflare's daily neuron quota. The run-1 files were re-attached via `scripts/recover_compare_images.py` (clustered by mtime, VLM-ranked winners), so the posts carry AI-generated featured + inpost images.")
    L.append("- Old-side per-post image time is not attributed: `image_logs` subjects are topic fragments, not article titles, so they cannot be mapped to baseline posts.")
    L.append("")
    return L


# ---------- judge ----------

def judge_one(art: dict) -> dict:
    body = (art.get("markdown") or art.get("html") or "")[:14000]
    payload_body = f"TITLE: {art['title']}\nMETA: {art.get('excerpt','')}\n\nBODY:\n{body}"
    last_err = None
    for model in JUDGE_MODELS:
        for attempt in range(2):
            try:
                r = requests.post(JUDGE_URL, json={
                    "model": model,
                    "temperature": 0,
                    "messages": [
                        {"role": "system", "content": JUDGE_RUBRIC},
                        {"role": "user", "content": payload_body},
                    ],
                }, headers={"Authorization": f"Bearer {os.environ['GEMINI_API_KEY']}"},
                    timeout=90)
                r.raise_for_status()
                txt = r.json()["choices"][0]["message"]["content"]
                m = re.search(r"\{.*\}", txt, re.S)
                data = json.loads(m.group(0))
                data["_model"] = model
                return data
            except Exception as e:
                last_err = e
                time.sleep(2 + attempt * 3)
    print(f"  ! judge failed: {last_err}")
    return {"facts": {"score": None}, "tone": {"score": None}, "style": {"score": None}, "_model": f"error:{last_err}"}


def judge_scores(art: dict, cache: dict) -> dict:
    key = hashlib.sha1((art["title"] + (art.get("markdown") or "")[:6000]).encode("utf-8", "ignore")).hexdigest()
    if key in cache.get("judge", {}):
        return cache["judge"][key]
    res = judge_one(art)
    cache.setdefault("judge", {})[key] = res
    save_cache(cache)
    print(f"    judged {art['title'][:60]!r} -> f={res['facts'].get('score')} t={res['tone'].get('score')} s={res['style'].get('score')} ({res.get('_model')})")
    return res


def save_cache(cache: dict):
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


def load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"judge": {}, "metrics": {}}


# ---------- aggregate + report ----------

def javg(arts_judged: list[dict], dim: str):
    vals = [j[dim]["score"] for j in arts_judged if j.get(dim, {}).get("score")]
    return round(mean(vals), 2) if vals else None


def avg_metric(rows: list[dict], key: str):
    vals = [r["metrics"].get(key) for r in rows if r["metrics"].get(key) is not None]
    return round(mean(vals), 2) if vals else None


def dim_scores(row: dict, judged: dict) -> dict:
    m, j = row["metrics"], judged
    facts = (j.get("facts", {}).get("score") or 0)
    tone = (j.get("tone", {}).get("score") or 0)
    style = (j.get("style", {}).get("score") or 0)
    return {
        "facts": facts / 5 * 100,
        "style": style / 5 * 100,
        "seo": m["seo_score"],
        "tone": tone / 5 * 100,
        "structure": m["structure_score"],
        "images": m["image_score"],
        "length": m["length_score"],
    }


def weighted(d: dict) -> float:
    return round(sum(WEIGHTS[k] * d.get(k, 0) for k in WEIGHTS) / sum(WEIGHTS.values()), 1)


def fmt(v, nd=1):
    return "-" if v is None else (f"{v:.{nd}f}" if isinstance(v, float) else str(v))


def build_report(old_rows, new_rows, old_judged, new_judged, old_checks, new_checks, cache) -> str:
    def agg(rows, judged_list):
        dims = {}
        for k in WEIGHTS:
            if k in ("facts", "tone", "style"):
                vals = [j[k]["score"] for j in judged_list if j.get(k, {}).get("score")]
                dims[k] = round(mean(vals) / 5 * 100, 1) if vals else 0
            else:
                dims[k] = mean([dim_scores(r, j)[k] for r, j in zip(rows, judged_list)])
        return dims

    o_d, n_d = agg(old_rows, old_judged), agg(new_rows, new_judged)
    o_w, n_w = weighted(o_d), weighted(n_d)

    L = []
    L.append("# Engine vs. Baseline — ContentFTE new output vs. old ContentSpark output\n")
    L.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M')} · baseline = last {len(old_rows)} published posts from the Google Sheet · new = {len(new_rows)} article(s) from the ContentFTE engine · judge = Gemini (identical rubric, temp 0)\n")

    L.append("## Verdict\n")
    L.append(f"**Weighted overall: old {o_w} / 100 vs new {n_w} / 100 → {'NEW' if n_w >= o_w else 'OLD'} wins by {abs(round(n_w - o_w, 1))}**\n")
    L.append("| Dimension | Weight | Old (baseline) | New (engine) | Delta | Winner |")
    L.append("|---|---:|---:|---:|---:|---|")
    for k, w in WEIGHTS.items():
        o, n = o_d[k], n_d[k]
        win = "-" if abs(o - n) < 1 else ("new" if n > o else "old")
        L.append(f"| {k} | {w}% | {o:.1f} | {n:.1f} | {n - o:+.1f} | {win} |")
    L.append("")

    L.append("## Objective metrics (averages)\n")
    keys = ["words", "h2", "faq_count", "ext_links", "int_links", "images", "image_alt_pct",
            "ai_hits_per_1k", "passive_per_100", "flesch", "fkgl", "intro_words",
            "para_avg_words", "meta_chars", "title_chars", "seo_score", "structure_score"]
    L.append("| Metric | Old avg | New avg | Better |")
    L.append("|---|---:|---:|---|")
    for k in keys:
        o, n = avg_metric(old_rows, k), avg_metric(new_rows, k)
        if o is None and n is None:
            continue
        better = "-"
        if o is not None and n is not None:
            lower_better = k in ("ai_hits_per_1k", "passive_per_100", "fkgl", "intro_words", "para_avg_words", "title_chars")
            if k == "title_chars":
                def band(v): return 1 if 30 <= v <= 75 else 0
                better = "tie" if band(o) == band(n) else ("old" if band(o) else "new")
            elif k == "meta_chars":
                def band2(v): return 1 if 70 <= v <= 165 else 0
                better = "tie" if band2(o) == band2(n) else ("old" if band2(o) else "new")
            else:
                better = "tie" if abs(o - n) < 0.05 else (("old" if (o > n) != lower_better else "new"))
        L.append(f"| {k} | {fmt(o)} | {fmt(n)} | {better} |")
    L.append("")

    L.extend(ops_lines(old_rows, new_rows))

    L.append("## Judge scores (1–5, harsh rubric)\n")
    L.append("| Dimension | Old avg | New avg |")
    L.append("|---|---:|---:|")
    for k in ("facts", "tone", "style"):
        L.append(f"| {k} | {fmt(javg(old_judged, k), 2)} | {fmt(javg(new_judged, k), 2)} |")
    L.append("")

    if new_checks or old_checks:
        L.append("## Published-page checks (supplementary, not weighted)\n")
        L.append("| Article | URL status | Title len | Meta desc | JSON-LD types | OG | H1s |")
        L.append("|---|---|---:|---|---|---|---:|")
        for label, checks in (("old", old_checks), ("new", new_checks)):
            for u, c in checks.items():
                if "error" in c:
                    L.append(f"| {label} | {u[-48:]} | - | error: {c['error']} | - | - | - |")
                else:
                    L.append(f"| {label} | {u[-48:]} | {c.get('title_len','')} | {'yes' if c.get('meta_desc') else 'NO'} ({c.get('meta_len','')}) | {', '.join(c.get('ld_types') or []) or '-'} | {'y' if c.get('og') else 'n'} | {c.get('h1_count','')} |")
        L.append("")

    L.append("## New engine articles (detail)\n")
    for r, j in zip(new_rows, new_judged):
        m = r["metrics"]
        t = r["meta"]
        L.append(f"### {t['title']}\n")
        L.append(f"- id {t.get('id')} · status `{t.get('status')}` · cost ${t.get('cost_usd', 0):.4f} · engine scores `{json.dumps(t.get('engine_scores', {}))}`")
        L.append(f"- words {m['words']} · H2 {m['h2']} · FAQ {m['faq_count']} · links ext/int {m['ext_links']}/{m['int_links']} · images {m['images']} ({m['image_alt_pct']}% alt)")
        L.append(f"- readability Flesch {m['flesch']} / grade {m['fkgl']} · AI-isms/1k {m['ai_hits_per_1k']} · passive/100 {m['passive_per_100']}")
        L.append(f"- seo {m['seo_score']} · structure {m['structure_score']} · length score {m['length_score']} · judge f/t/s {j.get('facts',{}).get('score')}/{j.get('tone',{}).get('score')}/{j.get('style',{}).get('score')}")
        if j.get("facts", {}).get("issues"):
            L.append(f"- judge issues — facts: {j['facts']['issues']} · tone: {j['tone'].get('issues','')} · style: {j['style'].get('issues','')}")
        L.append(f"- url: {t.get('url','-')}")
        L.append("")

    L.append("## Old baseline articles (appendix)\n")
    L.append("| # | Title | Words | H2 | FAQ | Links ext | Images | SEO | Struct | Flesch | AI/1k | Judge f/t/s |")
    L.append("|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for i, (r, j) in enumerate(zip(old_rows, old_judged), 1):
        m = r["metrics"]
        L.append(f"| {i} | {r['meta']['title'][:58]} | {m['words']} | {m['h2']} | {m['faq_count']} | {m['ext_links']} | {m['images']} | {m['seo_score']} | {m['structure_score']} | {m['flesch']} | {m['ai_hits_per_1k']} | {j.get('facts',{}).get('score','-')}/{j.get('tone',{}).get('score','-')}/{j.get('style',{}).get('score','-')} |")
    L.append("")

    L.append("## Methodology & limitations\n")
    L.append("- Baseline = `ContentSpark/generated_posts` rows with `Published=Yes` (last 25 by `Created At`); body = the markdown the old agent produced.")
    L.append("- New = last 3 published/approved articles from the engine (`/sdk/v1` delivery payload).")
    L.append("- Objective metrics computed with the identical parser for both sides (word/heading/link/image counts, Flesch/FKGL, AI-cliché & passive counters, SEO/structure checklists).")
    L.append("- Facts/tone/style = one Gemini judge call per article, same rubric, temperature 0. Facts judged **without live web search** — plausibility/consistency only; the engine's own Tavily fact-check gate runs separately on new articles.")
    L.append("- Judge knowledge cutoff: very recent model releases postdate the judge — it scored the new Haiku-5.5 article f=1 (\"models do not exist\") and the old DeepSeek-V4.1-Flash article f=1 the same way, so the artifact hits **both** sides but adds noise to the facts dimension.")
    L.append("- Old image provenance = sheet `Image Source` (stock); alt-% from markdown `![](url)` alt text. Published-page checks are supplementary (network-dependent) and not weighted.")
    L.append(f"- Weights: {json.dumps(WEIGHTS)}. Judge model(s): {', '.join(JUDGE_MODELS)}.")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old-limit", type=int, default=25)
    ap.add_argument("--site", default="", help="engine site slug filter for new articles")
    ap.add_argument("--new-limit", type=int, default=3)
    ap.add_argument("--metrics-only", action="store_true")
    ap.add_argument("--report-only", action="store_true")
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--out", default=str(REPORT_PATH))
    args = ap.parse_args()

    cache = load_cache()

    if args.report_only:
        old_rows = cache["old_rows"]
        new_rows = cache["new_rows"]
        old_j, new_j = cache["old_judged"], cache["new_judged"]
        old_checks, new_checks = cache.get("old_checks", {}), cache.get("new_checks", {})
    else:
        print("Fetching old articles from sheet...")
        old = fetch_old(args.old_limit)
        print(f"  {len(old)} published articles (of last {args.old_limit})")
        print("Fetching new articles from engine...")
        new = fetch_new(args.site, args.new_limit)
        print(f"  {len(new)} new articles: {[a['title'] for a in new]}")
        if not new:
            print("  (none yet — run generation first, then rerun)")
        old_rows = [{"meta": a, "metrics": compute_metrics(a)} for a in old]
        new_rows = [{"meta": a, "metrics": compute_metrics(a)} for a in new]

        if args.no_fetch:
            old_checks, new_checks = {}, {}
        else:
            print("Published-page checks...")
            old_checks = fetch_checks([a.get("url", "") for a in old])
            new_checks = fetch_checks([a.get("url", "") for a in new])
            print(f"  old ok {sum(1 for c in old_checks.values() if 'error' not in c)}/{len(old_checks)}, new ok {sum(1 for c in new_checks.values() if 'error' not in c)}/{len(new_checks)}")
            for rows, checks in ((old_rows, old_checks), (new_rows, new_checks)):
                for r in rows:
                    c = checks.get(r["meta"].get("url", ""))
                    if c and "img_count" in c:
                        m = r["metrics"]
                        m["images"] = c["img_count"]
                        m["image_alt_pct"] = c["img_alt_pct"]
                        m["image_score"] = (40 if c["img_count"] >= 1 else 0) + \
                            (40 if c["img_count"] and c["img_alt_pct"] >= 80 else 0) + \
                            (20 if c["img_count"] >= 2 else 0)

        old_j, new_j = [], []
        if not args.metrics_only:
            print("Judging old articles...")
            for i, a in enumerate(old, 1):
                print(f"  [{i}/{len(old)}] {a['title'][:60]!r}")
                old_j.append(judge_scores(a, cache))
            print("Judging new articles...")
            for a in new:
                new_j.append(judge_scores(a, cache))
        else:
            old_j = [cache.get("judge", {}).get(hashlib.sha1((a["title"] + a.get("markdown", "")[:6000]).encode("utf-8", "ignore")).hexdigest(), {"facts": {}, "tone": {}, "style": {}}) for a in old]
            new_j = [cache.get("judge", {}).get(hashlib.sha1((a["title"] + a.get("markdown", "")[:6000]).encode("utf-8", "ignore")).hexdigest(), {"facts": {}, "tone": {}, "style": {}}) for a in new]

        cache.update({
            "old_rows": [{**r, "metrics": r["metrics"]} for r in old_rows],
            "new_rows": [{**r, "metrics": r["metrics"]} for r in new_rows],
            "old_judged": old_j, "new_judged": new_j,
            "old_checks": old_checks, "new_checks": new_checks,
        })
        save_cache(cache)

    report = build_report(old_rows, new_rows, old_j, new_j, old_checks, new_checks, cache)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"\nReport written: {out}")
    o_w = weighted({k: 0 for k in WEIGHTS})
    print("Done.")


if __name__ == "__main__":
    main()
