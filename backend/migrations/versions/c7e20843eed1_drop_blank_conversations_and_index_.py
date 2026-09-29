"""drop blank conversations and index thread recency

Every press of "New chat" used to create a conversation row whether or not
anything was ever said in it. Those blanks were hidden by the client but still
counted against the sidebar's page size, so a customer with enough of them saw
an empty history. The rows carry no content, so removing them loses nothing.

Also adds the index behind the sidebar query, which orders a customer's threads
by most recent use.

Revision ID: c7e20843eed1
Revises: c23d03c9453c
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7e20843eed1"
down_revision: str | Sequence[str] | None = "c23d03c9453c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "DELETE FROM conversations c "
        "WHERE NOT EXISTS (SELECT 1 FROM messages m WHERE m.conversation_id = c.id)"
    )
    # Backfill titles for threads that predate the agent naming them, so old
    # history reads as the customer's own words rather than "New conversation".
    op.execute(
        "UPDATE conversations c SET title = left(m.content, 80) "
        "FROM ("
        "  SELECT DISTINCT ON (conversation_id) conversation_id, content"
        "  FROM messages WHERE role = 'user' ORDER BY conversation_id, id"
        ") m WHERE m.conversation_id = c.id AND c.title IS NULL"
    )
    op.create_index(
        "conversations_user_recent",
        "conversations",
        ["user_id", sa.text("updated_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("conversations_user_recent", table_name="conversations")
