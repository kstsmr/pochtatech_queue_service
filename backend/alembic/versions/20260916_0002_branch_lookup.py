"""Make active branch codes unambiguous.

Revision ID: 20260916_0002
Revises: 20260915_0001
Create Date: 2026-09-16
"""

from alembic import op

revision = "20260916_0002"
down_revision = "20260915_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("uq_branches_postal_code", "branches", ["postal_code"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_branches_postal_code", table_name="branches")
