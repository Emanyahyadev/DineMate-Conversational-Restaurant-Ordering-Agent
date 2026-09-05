import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import chat, menu
from app.config import settings
from app.db.postgres import init_db


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await init_db()
    except Exception as exc:  # noqa: BLE001 - let the app boot without Postgres in dev
        logger.warning("Postgres not reachable (%s); /api/chat will fail until it is.", exc)
    yield


app = FastAPI(title="Restaurant Ordering Agent", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router)
app.include_router(menu.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
