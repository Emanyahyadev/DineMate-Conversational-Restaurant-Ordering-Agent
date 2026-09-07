from __future__ import annotations

import os

import pytest

os.environ.setdefault("USE_FAKE_LLM", "true")
os.environ.setdefault("TESTING", "true")

import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.config import settings  # noqa: E402

settings.use_fake_llm = True
settings.testing = True
settings.local_postgres_url = (
    settings.local_postgres_url
    or "postgresql+asyncpg://dinemate:dinemate@localhost:5433/dinemate"
)

from app.db.models import (  # noqa: E402
    Cart,
    ConfirmationToken,
    Conversation,
    Order,
    OrderEvent,
    OrderLine,
    Session,
    User,
)
from app.db.postgres import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402


@pytest_asyncio.fixture
async def db():
    async with SessionLocal() as session:
        yield session


@pytest_asyncio.fixture(autouse=True)
async def clean_db():
    """Truncate transactional tables between tests; the menu is left seeded."""
    from sqlalchemy import delete

    async with SessionLocal() as session:
        for model in (
            OrderEvent,
            OrderLine,
            Order,
            ConfirmationToken,
            Cart,
            Conversation,
            Session,
            User,
        ):
            await session.execute(delete(model))
        await session.commit()
    yield


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def register_and_login(client: AsyncClient, email: str, password: str = "correct-horse-battery") -> AsyncClient:
    """Returns the client with auth + CSRF wired up."""
    r = await client.post(
        "/api/auth/register", json={"email": email, "password": password}
    )
    assert r.status_code == 201, r.text
    csrf = client.cookies.get("dm_csrf")
    client.headers["X-CSRF-Token"] = csrf
    return client
