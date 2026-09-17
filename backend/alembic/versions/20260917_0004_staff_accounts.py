"""Add branch-scoped staff accounts and revocable sessions.

Revision ID: 20260917_0004
Revises: 20260917_0003
Create Date: 2026-09-17
"""

from alembic import op

revision = "20260917_0004"
down_revision = "20260917_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS staff_members (
            id uuid PRIMARY KEY,
            branch_id uuid NOT NULL REFERENCES branches(id),
            employee_code text NOT NULL,
            display_name text NOT NULL,
            role text NOT NULL CHECK (role IN ('operator', 'manager')),
            pin_salt bytea NOT NULL,
            pin_hash bytea NOT NULL,
            active boolean NOT NULL DEFAULT true,
            failed_login_count integer NOT NULL DEFAULT 0 CHECK (failed_login_count >= 0),
            locked_until timestamptz,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (branch_id, id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS staff_members_branch_code
            ON staff_members(branch_id, lower(employee_code));
        CREATE INDEX IF NOT EXISTS staff_members_active_branch
            ON staff_members(branch_id, role) WHERE active;

        ALTER TABLE staff_sessions ADD COLUMN IF NOT EXISTS staff_member_id uuid;
        ALTER TABLE staff_sessions ADD COLUMN IF NOT EXISTS revoked_at timestamptz;
        DO $$ BEGIN
            ALTER TABLE staff_sessions ADD CONSTRAINT staff_sessions_member_fkey
                FOREIGN KEY (branch_id, staff_member_id)
                REFERENCES staff_members(branch_id, id);
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        CREATE INDEX IF NOT EXISTS staff_sessions_member_active
            ON staff_sessions(staff_member_id, expires_at)
            WHERE revoked_at IS NULL;
        UPDATE staff_sessions SET revoked_at = clock_timestamp()
            WHERE staff_member_id IS NULL AND revoked_at IS NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS staff_sessions_member_active;
        ALTER TABLE staff_sessions DROP CONSTRAINT IF EXISTS staff_sessions_member_fkey;
        ALTER TABLE staff_sessions DROP COLUMN IF EXISTS revoked_at;
        ALTER TABLE staff_sessions DROP COLUMN IF EXISTS staff_member_id;
        DROP TABLE IF EXISTS staff_members;
        """
    )
