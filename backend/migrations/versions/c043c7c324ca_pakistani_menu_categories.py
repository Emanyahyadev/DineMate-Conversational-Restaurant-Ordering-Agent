"""pakistani menu categories

Alembic does not detect a changed CHECK constraint, so this is written by hand:
autogenerate produced an empty migration and the seed then failed against the
old constraint.

Revision ID: c043c7c324ca
Revises: f04ff57e5e4e
Create Date: 2026-09-07 16:27:55.672676
"""

from typing import Sequence, Union

from alembic import op

revision: str = "c043c7c324ca"
down_revision: Union[str, Sequence[str], None] = "f04ff57e5e4e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD = "'Starters','Pizza','Pasta','Salad','Sides','Dessert','Drinks'"
NEW = (
    "'Starters','BBQ','Karahi & Curries','Biryani & Rice',"
    "'Breads','Sides','Desserts','Drinks'"
)


def upgrade() -> None:
    op.drop_constraint("menu_items_category_valid", "menu_items", type_="check")
    op.create_check_constraint(
        "menu_items_category_valid", "menu_items", f"category IN ({NEW})"
    )


def downgrade() -> None:
    # Rows in a category the old constraint forbids must go first, or the
    # constraint cannot be re-added.
    op.execute(f"DELETE FROM menu_items WHERE category NOT IN ({OLD})")
    op.drop_constraint("menu_items_category_valid", "menu_items", type_="check")
    op.create_check_constraint(
        "menu_items_category_valid", "menu_items", f"category IN ({OLD})"
    )
