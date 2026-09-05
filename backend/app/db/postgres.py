"""Short term memory: conversation turns stored in Postgres (Neon)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import settings

engine = create_async_engine(settings.postgres_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def ensure_conversation(session: AsyncSession, conversation_id: str | None, user_id: str) -> str:
    if conversation_id:
        existing = await session.get(Conversation, conversation_id)
        if existing:
            return existing.id
    conversation = Conversation(id=conversation_id or str(uuid.uuid4()), user_id=user_id)
    session.add(conversation)
    await session.flush()
    return conversation.id


async def get_history(session: AsyncSession, conversation_id: str, limit: int = 20) -> list[dict]:
    """Return the last `limit` turns, oldest first, as OpenAI-style messages."""
    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.id.desc())
        .limit(limit)
    )
    rows = list(result.scalars())[::-1]
    return [{"role": m.role, "content": m.content} for m in rows]


async def append_message(session: AsyncSession, conversation_id: str, role: str, content: str) -> None:
    session.add(Message(conversation_id=conversation_id, role=role, content=content))
