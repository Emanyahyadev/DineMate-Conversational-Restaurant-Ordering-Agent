"""backfill order groups for pre-split orders

Orders written before checkout could span kitchens have no ``order_group_id``.
Each of them was, factually, its own checkout - one basket, one kitchen, one
order - so each gets its own group. This is what lets INV-8 be checked per
checkout rather than per order.

Revision ID: c23d03c9453c
Revises: 0f1f29b99e67
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c23d03c9453c"
down_revision: str | Sequence[str] | None = "0f1f29b99e67"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # gen_random_uuid() per row, so each legacy order becomes its own checkout
    # rather than all of them collapsing into one.
    op.execute(
        "UPDATE orders SET order_group_id = gen_random_uuid() "
        "WHERE order_group_id IS NULL"
    )


def downgrade() -> None:
    # Nothing to undo: the column itself is dropped by the migration that added it.
    pass
