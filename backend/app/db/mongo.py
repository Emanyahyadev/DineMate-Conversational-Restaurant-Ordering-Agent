"""MongoDB connection. Holds exactly one thing: per-user memory profiles.

The client is created lazily and cached per event loop. Motor binds a client to
the loop that created it, so a module-level client breaks anywhere the loop is
replaced (tests, workers restarted in-process).
"""

from __future__ import annotations

import asyncio
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection

from app.config import settings

_clients: dict[int, AsyncIOMotorClient] = {}


def get_client() -> AsyncIOMotorClient:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    key = id(loop)

    client = _clients.get(key)
    if client is None:
        client = AsyncIOMotorClient(
            settings.active_mongodb_url,
            serverSelectionTimeoutMS=2000,  # memory is degradable, not blocking
            connectTimeoutMS=2000,
        )
        _clients[key] = client
    return client


class _ProfilesProxy:
    """Resolves the collection at call time, on the current loop."""

    def _collection(self) -> AsyncIOMotorCollection:
        return get_client()[settings.mongodb_db]["profiles"]

    def __getattr__(self, name: str) -> Any:
        return getattr(self._collection(), name)

    @property
    def database(self) -> Any:
        return get_client()[settings.mongodb_db]


profiles = _ProfilesProxy()
