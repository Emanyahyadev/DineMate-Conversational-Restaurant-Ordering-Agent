"""MongoDB connection. Holds exactly one thing: per-user memory profiles.

The client is created lazily and cached per event loop. Motor binds a client to
the loop that created it, so a module-level client breaks anywhere the loop is
replaced (tests, workers restarted in-process).
"""

from __future__ import annotations

import asyncio
import weakref
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection

from app.config import settings

# Keyed by the loop object, weakly.
#
# This was keyed by ``id(loop)``, which is only safe while the loop is alive:
# once a loop is collected CPython is free to hand its address to the next
# object, and a new loop landing on a recycled id would be given a client bound
# to a loop that no longer exists. A weak-keyed map also lets the entry go when
# the loop does, instead of holding a dead client for the life of the process.
_clients: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, AsyncIOMotorClient] = (
    weakref.WeakKeyDictionary()
)
_no_loop_client: AsyncIOMotorClient | None = None


def _new_client() -> AsyncIOMotorClient:
    return AsyncIOMotorClient(
        settings.active_mongodb_url,
        serverSelectionTimeoutMS=2000,  # memory is degradable, not blocking
        connectTimeoutMS=2000,
        # Long-term memory is one small document per turn. A large pool buys
        # nothing and, multiplied across instances, is how an Atlas cluster
        # reaches its connection limit.
        maxPoolSize=settings.mongo_max_pool_size,
        maxIdleTimeMS=60_000,
    )


def get_client() -> AsyncIOMotorClient:
    global _no_loop_client
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        if _no_loop_client is None:
            _no_loop_client = _new_client()
        return _no_loop_client

    client = _clients.get(loop)
    if client is None:
        client = _new_client()
        _clients[loop] = client
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
