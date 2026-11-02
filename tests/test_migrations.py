"""ENG-15 / OPS-01: Alembic is wired to the engine's models and database URL."""
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _alembic(db_url, *args):
    import os
    env = {**os.environ, "DATABASE_URL": db_url}
    return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=ROOT, env=env, capture_output=True, text=True,
                          timeout=120)


def _tables(path):
    con = sqlite3.connect(path)
    try:
        return {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    finally:
        con.close()


def test_upgrade_head_builds_every_table_on_an_empty_database(tmp_path):
    db = tmp_path / "fresh.db"
    out = _alembic(f"sqlite:///{db.as_posix()}", "upgrade", "head")
    assert out.returncode == 0, out.stderr[-500:]
    tables = _tables(db)
    assert {"sites", "articles", "api_keys", "leases", "idempotency_records", "alembic_version"} <= tables


def test_an_existing_database_can_be_stamped_without_touching_its_data(tmp_path):
    import os
    import lib.db as db_mod
    db = tmp_path / "existing.db"
    url = f"sqlite:///{db.as_posix()}"
    old = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    if db_mod._engine is not None:
        db_mod._engine.dispose()
    db_mod._engine = None
    db_mod._SessionLocal = None
    try:
        db_mod.init_db()                                           # what the engine does today
        s = db_mod.get_session()
        s.add(db_mod.Site(slug="keepme", name="K"))
        s.commit()
        s.close()
    finally:
        db_mod._engine.dispose()
        db_mod._engine = None
        db_mod._SessionLocal = None
        if old is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old
    assert _alembic(url, "stamp", "0001").returncode == 0
    assert _alembic(url, "upgrade", "head").returncode == 0        # no-op: tables already exist
    cur = _alembic(url, "current")
    assert "0001" in (cur.stdout + cur.stderr)
    con = sqlite3.connect(db)
    assert con.execute("select slug from sites").fetchall() == [("keepme",)]
    con.close()


def test_the_baseline_refuses_to_downgrade(tmp_path):
    db = tmp_path / "d.db"
    url = f"sqlite:///{db.as_posix()}"
    assert _alembic(url, "upgrade", "head").returncode == 0
    assert _alembic(url, "downgrade", "base").returncode != 0
    assert "sites" in _tables(db)                                   # nothing was dropped
