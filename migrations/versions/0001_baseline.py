"""baseline: the schema as of the Alembic introduction

Revision ID: 0001
Revises:
Create Date: 2026-11-02

Until now the schema was created by `Base.metadata.create_all` and a column added later never reached an existing
database (there was no migration tool). This revision is the starting point: on an EMPTY database it creates every
table; on a database the engine already created it is a no-op (`checkfirst`), and you simply stamp it:

    alembic stamp 0001        # existing database: record "already at baseline"
    alembic upgrade head      # new database: build it (or let the engine's init_db do that)

From here on, every schema change is a numbered revision file in this folder instead of an unrecorded drift.
"""
from alembic import op

from lib.db import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    raise RuntimeError("the baseline cannot be downgraded: it would drop every table")
