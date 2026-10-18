"""Backfill brain/*.md into the brain_entries table (idempotent by title)."""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass
from pathlib import Path

from lib.db import get_session, init_db, BrainEntry
from sqlalchemy import select

BRAIN_DIR = Path(__file__).resolve().parents[1] / "brain"


def main():
    init_db()
    s = get_session()
    imported = 0
    skipped = 0
    try:
        if not BRAIN_DIR.is_dir():
            print("no brain dir"); return
        for p in sorted(BRAIN_DIR.glob("*.md")):
            if p.name == "README.md" or p.name.startswith("_"):
                continue
            text = p.read_text(encoding="utf-8")
            title = ""
            tags = []
            for line in text.splitlines()[:12]:
                sl = line.strip()
                if sl.startswith("# ") and not title:
                    title = sl[2:].strip()
                if sl.lower().startswith("tags:"):
                    tags = [t.strip() for t in sl[5:].split(",") if t.strip()]
            if not title:
                title = p.stem
            kind = "coverage" if p.name.startswith("coverage-") else "voice"
            existing = s.execute(
                select(BrainEntry).where(BrainEntry.title == title)
            ).scalar_one_or_none()
            if existing is not None:
                skipped += 1
                continue
            s.add(BrainEntry(kind=kind, title=title, tags=tags, content=text,
                             source="backfill"))
            imported += 1
        s.commit()
        print("imported=%d skipped=%d" % (imported, skipped))
    finally:
        s.close()


if __name__ == "__main__":
    raise SystemExit(main())