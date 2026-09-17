"""Add durable staff sessions and window ownership.

Revision ID: 20260917_0003
Revises: 20260916_0002
Create Date: 2026-09-17
"""

from alembic import op

revision = "20260917_0003"
down_revision = "20260916_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS staff_sessions (
            id uuid PRIMARY KEY,
            branch_id uuid NOT NULL REFERENCES branches(id),
            employee_code text NOT NULL,
            role text NOT NULL CHECK (role IN ('operator', 'manager')),
            token_hash text NOT NULL UNIQUE,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            expires_at timestamptz NOT NULL,
            CHECK (expires_at > created_at)
        );
        CREATE INDEX IF NOT EXISTS staff_sessions_branch
            ON staff_sessions(branch_id, expires_at);
        ALTER TABLE windows ADD COLUMN IF NOT EXISTS operator_session_id uuid;
        CREATE UNIQUE INDEX IF NOT EXISTS uq_windows_operator_session
            ON windows(operator_session_id) WHERE operator_session_id IS NOT NULL;

        DO $$ BEGIN
            ALTER TABLE windows ADD CONSTRAINT windows_operator_session_id_fkey
                FOREIGN KEY (operator_session_id) REFERENCES staff_sessions(id);
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;

        DO $$ BEGIN
            ALTER TABLE windows ADD CONSTRAINT window_operator_required
                CHECK ((status = 'closed') = (operator_session_id IS NULL));
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE windows DROP CONSTRAINT IF EXISTS window_operator_required;
        ALTER TABLE windows DROP CONSTRAINT IF EXISTS windows_operator_session_id_fkey;
        DROP INDEX IF EXISTS uq_windows_operator_session;
        ALTER TABLE windows DROP COLUMN IF EXISTS operator_session_id;
        DROP TABLE IF EXISTS staff_sessions;
        """
    )
