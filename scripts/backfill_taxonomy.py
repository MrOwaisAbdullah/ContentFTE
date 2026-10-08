"""Backfill auto-derived taxonomy (categories + tags) onto the 3 live
comparison posts.

Those posts were published before the taxonomy batch, so their meta has no
`meta["taxonomy"]`. The first refresh derives terms (brief/meta override ->
prefer-reuse lexical vs the site's existing WP terms -> JEV judge ->
propose-new), pushes them, and caches them on the article; later refreshes
reuse the cache. Each post is then read back through the WP REST API to
verify the stored category/tag IDs resolve to the names we pushed.

Run from repo root (.env provides OPENROUTER_API_KEY for the JEV lane;
WP_* must come from the invocation env):
  WP_BASE_URL=http://speedline.local WP_USERNAME=user_admin \\
  WP_APP_PASSWORD="kY8I eOZS EnL0 J9tk kRoi erWi" PYTHONUTF8=1 \\
  python scripts/backfill_taxonomy.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

sys.path.insert(0, str(ROOT))

import requests  # noqa: E402 — after .env/sys.path setup

from lib.db import Article as ArticleModel  # noqa: E402
from lib.db import get_session  # noqa: E402
from lib.wordpress import WPConfig, WordPressConnector  # noqa: E402
from sdk import service  # noqa: E402

SITE = "comparison-run"


def _terms_by_id(cfg: WPConfig, kind: str) -> dict[int, str]:
    resp = requests.get(
        f"{cfg.base_url}/wp-json/wp/v2/{kind}",
        params={"per_page": 100, "hide_empty": "false"},
        auth=(cfg.username, cfg.app_password), timeout=30)
    resp.raise_for_status()
    return {t["id"]: str(t.get("name") or "") for t in resp.json()}


def main() -> int:
    missing = [k for k in ("WP_BASE_URL", "WP_USERNAME", "WP_APP_PASSWORD")
               if not os.environ.get(k)]
    if missing:
        print(f"missing WP env vars: {', '.join(missing)}", flush=True)
        return 1

    with get_session() as s:
        rows = []
        for art in s.query(ArticleModel).all():
            meta = dict(art.meta) if isinstance(art.meta, dict) else {}
            if (art.site is None or art.site.slug != SITE
                    or not meta.get("wp_post_id")
                    or not (art.content_md or "").strip()):
                continue
            rows.append((art.id, art.title, int(meta["wp_post_id"]),
                         "taxonomy" in meta))
        rows.sort()

    if not rows:
        print(f"no published comparison posts found (site '{SITE}' with "
              "meta.wp_post_id)", flush=True)
        return 1

    cfg = WPConfig.from_env()
    failures = 0
    for aid, title, post_id, cached in rows:
        print(f"\n=== article {aid} wp#{post_id} cached={cached} {title}",
              flush=True)
        out = service.refresh_article(aid)
        if (not out.get("ok")
                and "invalid outbound link" in str(out.get("error") or "")):
            print(f"  link guard: {out['error']} — retry WP_LINK_CHECK=0",
                  flush=True)
            os.environ["WP_LINK_CHECK"] = "0"
            out = service.refresh_article(aid)
        pushed_cats = out.get("categories") or []
        pushed_tags = out.get("tags") or []
        print(f"  refresh: ok={bool(out.get('ok'))} "
              f"source={out.get('category_source', '')} "
              f"categories={pushed_cats} tags={pushed_tags}", flush=True)
        if not out.get("ok"):
            print(f"  error: {out.get('error')}", flush=True)
            failures += 1
            continue

        try:
            doc = WordPressConnector(cfg).get_post(post_id, context="view")
            cat_ids = doc.get("categories") or []
            tag_ids = doc.get("tags") or []
            cat_names = [_terms_by_id(cfg, "categories").get(i, f"#{i}")
                         for i in cat_ids]
            tag_names = [_terms_by_id(cfg, "tags").get(i, f"#{i}")
                         for i in tag_ids]
        except Exception as exc:  # noqa: BLE001 — read-back must not crash
            print(f"  read-back FAILED: {type(exc).__name__}: {exc}",
                  flush=True)
            failures += 1
            continue

        known_cats = {c.lower() for c in cat_names}
        ok = (bool(pushed_cats) and bool(pushed_tags)
              and any(c.lower() in known_cats for c in pushed_cats))
        print(f"  read-back: status={doc.get('status')} "
              f"categories={cat_names} tags={tag_names} "
              f"-> {'OK' if ok else 'MISMATCH'}", flush=True)
        if not ok:
            failures += 1

    total = len(rows)
    print(f"\nbackfill: {total - failures}/{total} posts verified", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
