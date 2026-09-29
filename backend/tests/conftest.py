from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("USE_FAKE_LLM", "true")
os.environ.setdefault("TESTING", "true")

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import settings

settings.use_fake_llm = True
settings.testing = True
settings.local_mongodb_url = settings.local_mongodb_url or "mongodb://localhost:27018"
settings.local_postgres_url = (
    settings.local_postgres_url
    or "postgresql+asyncpg://dinemate:dinemate@localhost:5433/dinemate"
)

from app.db.models import (  # noqa: E402
    Cart,
    ConfirmationToken,
    Conversation,
    MenuItem,
    Order,
    OrderEvent,
    OrderLine,
    OrderRating,
    Session,
    User,
)
from app.services import menu_service  # noqa: E402


def _seeded_item_ids() -> set[str]:
    """Dish ids that belong to the seed file.

    Read from seeds/restaurants.yaml rather than from the database: leftovers
    from an earlier interrupted run would otherwise be mistaken for seed data
    and kept forever.
    """
    import yaml

    path = Path(__file__).resolve().parent.parent / "seeds" / "restaurants.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {item["id"] for spec in data for item in spec.get("items", [])}


#: Dish ids that came from the seed. Anything else was created by a test.
_SEEDED_ITEM_IDS: set[str] = _seeded_item_ids()
from app.db.postgres import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402


@pytest_asyncio.fixture
async def db():
    async with SessionLocal() as session:
        yield session


@pytest_asyncio.fixture(autouse=True)
async def clean_db():
    """Truncate transactional tables between tests; the seeded menu stays.

    Dishes a test *created* do not stay. A restaurant can add to its own menu
    now, so without this a dish added by one test is still there for the next
    one, which quietly turns "added successfully" into a duplicate conflict.
    The seeded ids are captured on the first run, before any test has added
    anything, and everything else is removed.
    """
    from sqlalchemy import delete

    async with SessionLocal() as session:
        for model in (
            OrderRating,
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

        removed = await session.execute(
            delete(MenuItem).where(MenuItem.id.notin_(_SEEDED_ITEM_IDS))
        )
        if removed.rowcount:
            menu_service.invalidate_cache()

        await session.commit()
    yield


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def other_client():
    """A second, independent browser.

    Authorization tests need two sessions at once; logging a second user in on
    the same client just overwrites the first one's cookies, which quietly turns
    "the intruder was blocked" into "there was only ever one user".
    """
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
