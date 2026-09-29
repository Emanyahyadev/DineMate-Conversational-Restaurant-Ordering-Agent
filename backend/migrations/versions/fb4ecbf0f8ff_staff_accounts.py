"""staff accounts

Hand-finished: autogenerate produced an unconditional NOT NULL column (which
fails against existing rows) and omitted the CHECK constraints entirely, since
Alembic does not detect those.

Revision ID: fb4ecbf0f8ff
Revises: c043c7c324ca
Create Date: 2026-09-07 18:03:54.145194
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fb4ecbf0f8ff"
down_revision: str | Sequence[str] | None = "c043c7c324ca"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FK = "users_staff_restaurant_id_fkey"


def upgrade() -> None:
    # Expand/contract: add with a default so existing rows are valid, then drop
    # the default so the application is the only thing that sets it.
    op.add_column(
        "users",
        sa.Column("role", sa.String(length=16), nullable=False, server_default="customer"),
    )
    op.alter_column("users", "role", server_default=None)

    op.add_column(
        "users", sa.Column("staff_restaurant_id", sa.String(length=32), nullable=True)
    )
    op.create_foreign_key(
        FK, "users", "restaurants", ["staff_restaurant_id"], ["id"], ondelete="SET NULL"
    )

    op.create_check_constraint(
        "users_role_valid", "users", "role IN ('customer','staff')"
    )
    # Staff without a kitchen could see everything; a customer with one would be
    # staff by accident. Neither may exist.
    op.create_check_constraint(
        "users_staff_has_restaurant",
        "users",
        "(role = 'staff') = (staff_restaurant_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("users_staff_has_restaurant", "users", type_="check")
    op.drop_constraint("users_role_valid", "users", type_="check")
    op.drop_constraint(FK, "users", type_="foreignkey")
    op.drop_column("users", "staff_restaurant_id")
    op.drop_column("users", "role")
