"""Lean-schema migration for the Postgres (Neon) cutover.

Drops the sheet-showcase/redundant columns that now live in meta/cost_ledger
and folds `articles.scores` into `articles.meta["scores"]` before the column
is removed. Adds the hot-path indexes.

Idempotent: safe to re-run. Operates on DATABASE_URL (Neon) by default; pass
--url to target another database. Does NOT touch the legacy sqlite file.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # noqa: BLE001
    pass

from sqlalchemy import create_engine, text


def _columns(conn, table):
    dialect = conn.dialect.name
    if dialect == "postgresql":
        rows = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=:t"
        ), {"t": table}).fetchall()
        return {r[0] for r in rows}
    rows = conn.execute(text("PRAGMA table_info(" + table + ")")).fetchall()
    return {r[1] for r in rows}


def _has_index(conn, name):
    dialect = conn.dialect.name
    if dialect == "postgresql":
        return bool(conn.execute(text(
            "SELECT 1 FROM pg_indexes WHERE indexname=:n"
        ), {"n": name}).fetchone())
    rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type='index'")).fetchall()
    return any(r[0] == name for r in rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("DATABASE_URL", ""))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not args.url:
        print("DATABASE_URL not set and --url not given", file=sys.stderr)
        return 2

    eng = create_engine(args.url, pool_pre_ping=True)
    with eng.begin() as conn:
        # 1. Fold articles.scores -> articles.meta["scores"] (only if the
        #    column still exists; idempotent).
        cols = _columns(conn, "articles")
        if "scores" in cols:
            if args.dry_run:
                print("[dry-run] would fold articles.scores -> meta['scores']")
            else:
                if conn.dialect.name == "postgresql":
                    conn.execute(text(
                        "UPDATE articles SET meta = (COALESCE(meta, '{}'::json)::jsonb "
                        "|| jsonb_build_object('scores', COALESCE(scores, '{}'::json)::jsonb))::json "
                        "WHERE (meta IS NULL OR meta->>'scores' IS NULL)"
                    ))
                else:
                    rows = conn.execute(text("SELECT id, meta, scores FROM articles")).fetchall()
                    for rid, meta, scores in rows:
                        m = json.loads(meta) if meta else {}
                        if "scores" not in m and scores:
                            m["scores"] = json.loads(scores) if isinstance(scores, str) else scores
                            conn.execute(text("UPDATE articles SET meta=:m WHERE id=:i"),
                                         {"m": json.dumps(m), "i": rid})
                print("folded articles.scores -> meta['scores']")

        # 2. Drop redundant/dead columns.
        drops = [
            ("sites", "publish_mode"),
            ("keyword_ledger", "cluster_id"),
            ("keyword_ledger", "target_url"),
            ("articles", "cost_usd"),
            ("articles", "content_html"),
            ("articles", "scores"),
        ]
        for table, col in drops:
            if col in _columns(conn, table):
                if args.dry_run:
                    print("[dry-run] would drop " + table + "." + col)
                else:
                    conn.execute(text("ALTER TABLE " + table + " DROP COLUMN " + col))
                    print("dropped " + table + "." + col)

        # 3. Hot-path indexes.
        indexes = [
            ("ix_kw_site_status", "keyword_ledger", "site_id, status"),
            ("ix_articles_site_status", "articles", "site_id, status"),
            ("ix_cost_article", "cost_ledger", "article_id"),
            ("ix_audit_action", "audit_log", "action"),
            ("ix_audit_article", "audit_log", "article_id"),
            ("ix_audit_site", "audit_log", "site_id"),
            ("ix_audit_created", "audit_log", "created_at"),
        ]
        for name, table, cols in indexes:
            if not _has_index(conn, name):
                if args.dry_run:
                    print("[dry-run] would create index " + name)
                else:
                    conn.execute(text("CREATE INDEX " + name + " ON " + table + " (" + cols + ")"))
                    print("created index " + name)

    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())