"""Re-run existing articles through the CURRENT quality gate (SEO-24).

    python scripts/audit_articles.py                      # every article that has content, all sites
    python scripts/audit_articles.py --site my-blog --status published
    python scripts/audit_articles.py --json > audit.json

Read-only: nothing is changed, approved, unpublished or refreshed. Posts written before the gates existed (or by
hand) get the same deterministic checks a new draft gets - fact-check against stored research, draft checks,
AEO lint, near-duplicates within the site - and the report says which ones would be refused today and why, so you
can decide what to rewrite first. Exit code 0 always (it is a report, not a gate).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from lib.db import Article, Site, get_session, init_db  # noqa: E402


def audit(site_slug: str = "", status: str = "", limit: int = 500) -> dict:
    from sdk import service

    init_db()
    s = get_session()
    results = []
    try:
        stmt = select(Article).order_by(Article.id.asc())
        if site_slug:
            site = s.execute(select(Site).where(Site.slug == site_slug)).scalar_one_or_none()
            if site is None:
                return {"error": f"site '{site_slug}' not found"}
            stmt = stmt.where(Article.site_id == site.id)
        if status:
            stmt = stmt.where(Article.status == status)
        for art in s.execute(stmt.limit(max(1, int(limit)))).scalars():
            if not (art.content_md or "").strip():
                continue
            gate = service._assess_gate(s, art)
            results.append({
                "id": art.id, "site_id": art.site_id, "title": art.title, "status": art.status,
                "pass": gate["pass"], "blocking": gate["blocking"], "warnings": gate["warnings"],
            })
    finally:
        s.close()
    failing = [r for r in results if not r["pass"]]
    return {"checked": len(results), "would_be_refused": len(failing),
            "clean": len(results) - len(failing), "articles": results}


def render(report: dict) -> str:
    if "error" in report:
        return f"error: {report['error']}"
    lines = [f"Checked {report['checked']} article(s): {report['clean']} clean, "
             f"{report['would_be_refused']} would be refused today.", ""]
    for r in report["articles"]:
        if r["pass"] and not r["warnings"]:
            continue
        mark = "REFUSED" if not r["pass"] else "warn"
        lines.append(f"#{r['id']} [{r['status']}] {r['title']!r}: {mark}")
        for b in r["blocking"]:
            lines.append(f"    - {b}")
        for w in r["warnings"]:
            lines.append(f"    ~ {w}")
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--site", default="")
    ap.add_argument("--status", default="")
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--json", action="store_true")
    ns = ap.parse_args()
    rep = audit(ns.site, ns.status, ns.limit)
    print(json.dumps(rep, indent=2, default=str) if ns.json else render(rep))
