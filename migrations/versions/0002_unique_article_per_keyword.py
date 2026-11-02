"""one article per (site, keyword)

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-02

Adds the partial UNIQUE index `uq_articles_site_keyword` (site_id, keyword_id WHERE keyword_id IS NOT NULL) that
closes the check-then-insert race in `submit_article` (ENG-12). New databases get it from the model; this brings an
existing one level.

It will NOT touch data. If the table already holds duplicates (the very bug this prevents) the index cannot be
built, and this revision stops with a clear message instead of deleting anything: list them with

    SELECT site_id, keyword_id, count(*) FROM articles
    WHERE keyword_id IS NOT NULL GROUP BY 1, 2 HAVING count(*) > 1;

merge or remove the extras by hand, then run `alembic upgrade head` again.
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

INDEX = "uq_articles_site_keyword"


def upgrade() -> None:
    bind = op.get_bind()
    existing = {ix["name"] for ix in sa.inspect(bind).get_indexes("articles")}
    if INDEX in existing:
        return
    dupes = bind.execute(sa.text(
        "SELECT site_id, keyword_id, count(*) AS n FROM articles WHERE keyword_id IS NOT NULL "
        "GROUP BY site_id, keyword_id HAVING count(*) > 1")).fetchall()
    if dupes:
        raise RuntimeError(
            f"{len(dupes)} (site, keyword) pair(s) already have more than one article, so the unique index "
            "cannot be created. Resolve them by hand (see this file's docstring for the query), then re-run.")
    op.create_index(INDEX, "articles", ["site_id", "keyword_id"], unique=True,
                    sqlite_where=sa.text("keyword_id IS NOT NULL"),
                    postgresql_where=sa.text("keyword_id IS NOT NULL"))


def downgrade() -> None:
    op.drop_index(INDEX, table_name="articles")
