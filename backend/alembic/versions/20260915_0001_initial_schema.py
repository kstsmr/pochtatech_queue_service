"""Create the durable queue schema.

Revision ID: 20260915_0001
Revises:
Create Date: 2026-09-15
"""

from pathlib import Path

from alembic import op

revision = "20260915_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    schema_path = Path(__file__).resolve().parents[3] / "docs" / "schema.sql"
    schema = schema_path.read_text(encoding="utf-8")
    schema = schema.removeprefix("-- Design specification, not an applied migration. Validate in an empty PostgreSQL database.\n")
    schema = schema.removeprefix("BEGIN;\n").removesuffix("COMMIT;\n")
    # Added by the following migration; strip it when bootstrapping from the evolving design document.
    schema = schema.replace("CREATE UNIQUE INDEX uq_branches_postal_code ON branches(postal_code);\n", "")
    op.execute(schema)


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS idempotency_requests;
        DROP TABLE IF EXISTS incidents;
        DROP TABLE IF EXISTS notification_log;
        DROP TABLE IF EXISTS ticket_events;
        DROP TABLE IF EXISTS tickets;
        DROP TABLE IF EXISTS priority_rules;
        DROP TABLE IF EXISTS client_sessions;
        DROP TABLE IF EXISTS appointment_slots;
        DROP TABLE IF EXISTS window_events;
        DROP TABLE IF EXISTS window_services;
        DROP TABLE IF EXISTS windows;
        DROP TABLE IF EXISTS staff_sessions;
        DROP TABLE IF EXISTS staff_members;
        DROP TABLE IF EXISTS branch_services;
        DROP TABLE IF EXISTS services;
        DROP TABLE IF EXISTS branch_working_hours;
        DROP TABLE IF EXISTS branches;
        """
    )
