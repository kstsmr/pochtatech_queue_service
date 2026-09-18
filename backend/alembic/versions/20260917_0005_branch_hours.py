"""Add weekly working hours for appointment generation.

Revision ID: 20260917_0005
Revises: 20260917_0004
Create Date: 2026-09-17
"""

from alembic import op

revision = "20260917_0005"
down_revision = "20260917_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS branch_working_hours (
            branch_id uuid NOT NULL REFERENCES branches(id),
            weekday smallint NOT NULL CHECK (weekday BETWEEN 0 AND 6),
            opens_at time,
            closes_at time,
            is_closed boolean NOT NULL DEFAULT false,
            PRIMARY KEY (branch_id, weekday),
            CHECK (
                (is_closed AND opens_at IS NULL AND closes_at IS NULL)
                OR
                (NOT is_closed AND opens_at IS NOT NULL AND closes_at IS NOT NULL
                    AND closes_at > opens_at)
            )
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS branch_working_hours;")
