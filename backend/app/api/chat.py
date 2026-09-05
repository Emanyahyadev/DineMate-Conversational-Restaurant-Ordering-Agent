from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agent.restaurant_agent import extract_memory, run_agent
from app.db import mongo
from app.db.postgres import SessionLocal, append_message, ensure_conversation, get_history

router = APIRouter(prefix="/api", tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    user_id: str = "guest"
    conversation_id: str | None = None


class ChatResponse(BaseModel):
    reply: str
    conversation_id: str


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest) -> ChatResponse:
    async with SessionLocal() as session:
        conversation_id = await ensure_conversation(session, payload.conversation_id, payload.user_id)
        history = await get_history(session, conversation_id)
        await session.commit()

    memory = await mongo.profile_summary(payload.user_id)

    try:
        reply = await run_agent(memory, history, payload.message, payload.user_id)
    except Exception as exc:  # noqa: BLE001 - surface LLM/tool failures to the client
        raise HTTPException(status_code=502, detail=f"Agent failed: {exc}") from exc

    async with SessionLocal() as session:
        await append_message(session, conversation_id, "user", payload.message)
        await append_message(session, conversation_id, "assistant", reply)
        await session.commit()

    extracted = await extract_memory(payload.message, reply)
    await mongo.remember(payload.user_id, extracted.preferences, extracted.facts)

    return ChatResponse(reply=reply, conversation_id=conversation_id)


@router.get("/conversations/{conversation_id}")
async def conversation_history(conversation_id: str) -> dict:
    async with SessionLocal() as session:
        return {"conversation_id": conversation_id, "messages": await get_history(session, conversation_id, limit=100)}


@router.get("/profile/{user_id}")
async def profile(user_id: str) -> dict:
    return await mongo.get_profile(user_id)
