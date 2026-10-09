"""enable timescaledb extension

Revision ID: 0d297f19dced
Revises:
Create Date: 2026-10-09 16:11:21.841169+00:00
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0d297f19dced"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The TimescaleDB image already creates the extension in POSTGRES_DB; IF NOT EXISTS keeps
    # this migration correct on any other PostgreSQL server that has TimescaleDB installed.
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS timescaledb")
