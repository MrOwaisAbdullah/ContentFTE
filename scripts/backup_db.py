"""Database backup with retention (OPS-01).

    python scripts/backup_db.py                       # DATABASE_URL -> backups/contentfte-<UTC stamp>.<ext>
    python scripts/backup_db.py --dir /mnt/backups --keep 14

* SQLite: uses the online-backup API (a consistent copy even while the engine is writing - copying the file
  with cp is NOT safe in WAL mode or mid-transaction).
* Postgres: runs `pg_dump --format=custom` (needs the client tools on PATH). On Neon, ALSO enable point-in-time
  restore in the project settings - a nightly dump is the floor, not the ceiling.

Old backups beyond `--keep` are deleted (oldest first). Prints the file written; never prints the URL (it carries
the password). Exit code 1 on failure so a scheduler can alert.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.db import database_url  # noqa: E402


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def backup_sqlite(url: str, out_dir: Path) -> Path:
    path = url.split("sqlite:///", 1)[1] if "sqlite:///" in url else ""
    if not path or path == ":memory:" or not os.path.exists(path):
        raise FileNotFoundError("the SQLite database file does not exist (nothing to back up)")
    dest = out_dir / f"contentfte-{_stamp()}.sqlite3"
    src = sqlite3.connect(path)
    try:
        dst = sqlite3.connect(str(dest))
        try:
            src.backup(dst)                       # consistent online copy
        finally:
            dst.close()
    finally:
        src.close()
    return dest


def backup_postgres(url: str, out_dir: Path) -> Path:
    if not shutil.which("pg_dump"):
        raise RuntimeError("pg_dump is not on PATH (install the PostgreSQL client tools)")
    dest = out_dir / f"contentfte-{_stamp()}.dump"
    # the URL goes to pg_dump through the environment, never on a command line another user could read
    env = {**os.environ, "PGCONNECT_TIMEOUT": "20"}
    url = url.replace("postgresql+psycopg://", "postgresql://").replace("postgres+psycopg://", "postgresql://")
    proc = subprocess.run(["pg_dump", "--format=custom", "--no-owner", "--file", str(dest), "--dbname", url],
                          env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        dest.unlink(missing_ok=True)
        raise RuntimeError("pg_dump failed: " + (proc.stderr or "")[:300].replace(url, "<database url>"))
    return dest


def prune(out_dir: Path, keep: int) -> list:
    files = sorted(out_dir.glob("contentfte-*.*"), key=lambda p: p.stat().st_mtime, reverse=True)
    removed = []
    for old in files[max(1, keep):]:
        old.unlink(missing_ok=True)
        removed.append(old.name)
    return removed


def run(out_dir: str = "backups", keep: int = 7) -> dict:
    url = database_url()
    folder = Path(out_dir)
    folder.mkdir(parents=True, exist_ok=True)
    if url.startswith("sqlite"):
        dest = backup_sqlite(url, folder)
    elif url.startswith(("postgres", "postgresql")):
        dest = backup_postgres(url, folder)
    else:
        raise ValueError("unsupported DATABASE_URL scheme")
    return {"file": str(dest), "bytes": dest.stat().st_size, "pruned": prune(folder, keep)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", default="backups")
    ap.add_argument("--keep", type=int, default=7)
    ns = ap.parse_args()
    try:
        print(run(ns.dir, ns.keep))
    except Exception as exc:  # noqa: BLE001
        print(f"backup FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
