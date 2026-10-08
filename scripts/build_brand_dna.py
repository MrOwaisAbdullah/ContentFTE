"""CLI (spec §5.1): (re)build a site's Brand DNA profile from samples.

Usage:
    python scripts/build_brand_dna.py --site my-site \\
        --file samples/about.md --file samples/post.txt \\
        --url https://example.com/about --text "pasted sample" \\
        [--dry-run]

Samples: local files (txt/md/html — tags stripped), fetched URLs, or
inline --text. Spec asks for 3-5 samples; fewer still works (warns),
none is an error. --dry-run prints the distilled profile without
saving; otherwise the profile is versioned into brand_profiles via
`save_profile` and the new version number is reported.

Pure distillation lives in `lib/brand_dna.distill_profile`; this file
is the thin I/O shell (files/URLs/DB), with injectable `llm_fn` so it
is testable offline.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import urllib.request
from typing import Any, Callable, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from lib.brand_dna import distill_profile, save_profile
from lib.db import Site, get_session, init_db

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean(raw: str) -> str:
    """Strip HTML tags and collapse whitespace (samples are prose voice,
    not layout)."""
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", raw or "")).strip()


def _read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        return _clean(fh.read())


def _fetch_url(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "ContentFTE/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return _clean(resp.read().decode(charset, errors="ignore"))


def build(*, files: Optional[List[str]] = None,
          urls: Optional[List[str]] = None,
          texts: Optional[List[str]] = None,
          dry_run: bool = False, site_slug: str = "",
          llm_fn: Optional[Callable[[str], str]] = None) -> Dict[str, Any]:
    """Collect samples → distill → (optionally) version into the DB."""
    init_db()
    samples: List[str] = []
    errors: List[str] = []
    for path in files or []:
        try:
            if body := _read_file(path):
                samples.append(body)
            else:
                errors.append(f"file '{path}' is empty after cleaning")
        except OSError as exc:
            errors.append(f"file '{path}': {exc}")
    for url in urls or []:
        try:
            if body := _fetch_url(url):
                samples.append(body)
            else:
                errors.append(f"url '{url}' returned empty content")
        except Exception as exc:  # urllib raises many types; fail per-sample
            errors.append(f"url '{url}': {exc}")
    for text in texts or []:
        if body := _clean(text):
            samples.append(body)
        else:
            errors.append("an inline --text sample was empty")

    if not samples:
        message = "no usable samples"
        if errors:
            message += " — " + "; ".join(errors)
        return {"status": "error", "message": message}
    if len(samples) < 3:
        logger.warning(
            "only %d sample(s) — spec §5.1 calls for 3-5; the profile "
            "will be thin", len(samples))

    try:
        profile = distill_profile(samples, llm_fn=llm_fn)
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    with get_session() as session:
        site = None
        if site_slug:
            site = session.execute(
                select(Site).where(Site.slug == site_slug)
            ).scalar_one_or_none()
            if site is None:
                return {"status": "error",
                        "message": f"site '{site_slug}' not found"}
        else:
            site = session.execute(
                select(Site).order_by(Site.id).limit(1)
            ).scalar_one_or_none()
            if site is None:
                return {"status": "error",
                        "message": "no site configured — create one first"}
        if dry_run:
            return {"status": "ok", "dry_run": True, "site": site.slug,
                    "samples_used": len(samples), "profile": profile}
        row = save_profile(session, site.id, profile)
        return {"status": "ok", "site": site.slug,
                "samples_used": len(samples), "version": row.version,
                "profile": dict(row.profile)}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(
        description="(Re)build a Brand DNA profile from samples (§5.1)")
    ap.add_argument("--site", default="", help="site slug (default: first site)")
    ap.add_argument("--file", action="append", default=[],
                    help="sample file path (repeatable)")
    ap.add_argument("--url", action="append", default=[],
                    help="sample URL to fetch (repeatable)")
    ap.add_argument("--text", action="append", default=[],
                    help="inline sample text (repeatable)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the profile without saving a new version")
    args = ap.parse_args()

    result = build(files=args.file, urls=args.url, texts=args.text,
                   dry_run=args.dry_run, site_slug=args.site)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
