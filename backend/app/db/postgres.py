"""Postgres engine and session factory.

Schema is owned by Alembic (DATA_MODEL.md section 7). There is deliberately no
``create_all`` here: it diverges silently from migrations.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import NullPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

# Under test every session gets its own connection: pooled asyncpg connections
# bound to a finished event loop blow up on reuse.
_pool_kwargs = (
    {"poolclass": NullPool}
    if settings.testing
    else {"pool_pre_ping": True, "pool_size": 10, "max_overflow": 20}
)

_url = settings.active_postgres_url

# Neon requires TLS. asyncpg does not understand libpq's ?sslmode=/channel_binding=
# query parameters, so they are stripped and expressed as a connect_arg instead.
_connect_args: dict[str, object] = {}
if "?" in _url:
    _url = _url.split("?", 1)[0]
if "neon.tech" in _url or "sslmode=require" in settings.active_postgres_url:
    _connect_args["ssl"] = "require"

# Neon's -pooler endpoint is PgBouncer in transaction mode. asyncpg prepares
# statements by default, and a prepared statement created on one pooled
# server connection is not visible on the next one, which shows up as hung or
# failing queries. Disabling the caches keeps every statement self-contained.
if "-pooler" in _url:
    _connect_args["statement_cache_size"] = 0
    _connect_args["prepared_statement_cache_size"] = 0

engine = create_async_engine(_url, connect_args=_connect_args, **_pool_kwargs)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a session that commits on success."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def ping() -> bool:
    from sqlalchemy import text

    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return True
