"""Chat (SSE), conversations and profile routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.agent.orchestrator import load_history, run_turn_stream
from app.api.deps import current_user_id, get_db, get_read_db, verify_csrf
from app.db.models import Conversation, Message, User
from app.services import auth_service, memory_service, order_service
from app.services.errors import NotFound

router = APIRouter(prefix="/api", tags=["chat"])


class ChatRequest(BaseModel):
    """Note there is no user_id here: identity comes from the session only."""

    message: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = None

    model_config = {"extra": "forbid"}


@router.post("/chat", dependencies=[Depends(verify_csrf)])
async def chat(payload: ChatRequest, user_id: str = Depends(current_user_id)):
    return EventSourceResponse(
        run_turn_stream(
            user_id=user_id,
            message=payload.message,
            conversation_id=payload.conversation_id,
        ),
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
        ping=15,
    )


@router.get("/greeting")
async def greeting(
    user_id: str = Depends(current_user_id), session: AsyncSession = Depends(get_read_db)
) -> dict:
    """The opening line, personalised from what DineMate already knows.

    Built server-side because the memory lives there: the client should not have
    to assemble a customer's own history in order to say hello properly.
    """
    user = await session.get(User, user_id)
    memories = await memory_service.list_memories(user_id)

    name = None
    for fact in memories["facts"]:
        if fact.get("kind") == "name" and fact.get("text"):
            name = fact["text"].replace("Prefers to be called", "").strip(" .")
            break
    if not name and user and user.display_name:
        name = user.display_name.split()[0]

    # Name the allergen, not the sentence it arrived in: stored phrasings vary
    # ("Allergic to peanuts" / "Nadia is allergic to peanuts.").
    allergens: list[str] = []
    for fact in memories["facts"]:
        if fact.get("kind") != "allergy":
            continue
        low = (fact.get("text") or "").lower()
        # Longest first, and skip a word already covered by a longer one:
        # otherwise "peanut" also matches "nut" and reads "peanut and nut".
        for word in sorted(memory_service.ALLERGEN_WORDS, key=len, reverse=True):
            if word not in low:
                continue
            if any(word in seen for seen in allergens):
                continue
            allergens.append(word)

    prefs = [p["text"] for p in memories["preferences"]][:2]
    orders = await order_service.list_orders(session, user_id, limit=1)

    hello = f"Hi {name}" if name else "Hi"
    knows: list[str] = []
    if allergens:
        listed = " and ".join(allergens)
        knows.append(f"your {listed} allergy is on file, so I will keep those off your suggestions")
    if prefs:
        knows.append("I have you down as " + " and ".join(p.lower() for p in prefs))

    if knows:
        detail = "; ".join(knows)
        detail = detail[:1].upper() + detail[1:]
        line = f"{hello}, welcome back. {detail}. What are you in the mood for?"
    elif orders:
        where = orders[0].restaurant_name
        line = (
            f"{hello}, welcome back."
            + (f" Your last order was from {where}." if where else "")
            + " What are you in the mood for?"
        )
    else:
        line = (
            f"{hello}, I am DineMate. I can show you what our restaurants are cooking, "
            "take your order, or check on one you have already placed. "
            "What are you in the mood for?"
        )

    return {
        "greeting": line,
        "name": name,
        "known_allergens": allergens,
        "known_preferences": prefs,
        "returning": bool(orders or allergens or prefs),
    }


@router.post("/conversations", status_code=201)
async def new_conversation(
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_db),
    _: None = Depends(verify_csrf),
) -> dict:
    """Start a fresh thread. Memory persists across conversations by design.

    Reuses the customer's existing blank thread if they already have one.
    Pressing "New chat" repeatedly should not litter the sidebar - and once
    enough blanks accumulate they push real threads past the list limit, which
    is what made history look like it was not being saved at all.
    """
    existing = await session.execute(
        select(Conversation)
        .where(
            Conversation.user_id == user_id,
            ~select(Message.id)
            .where(Message.conversation_id == Conversation.id)
            .exists(),
        )
        .order_by(Conversation.created_at.desc())
        .limit(1)
    )
    blank = existing.scalar_one_or_none()
    if blank is not None:
        return {"id": blank.id, "messages": []}

    conversation = Conversation(user_id=user_id)
    session.add(conversation)
    await session.flush()
    return {"id": conversation.id, "messages": []}


@router.get("/conversations")
async def list_conversations(
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_read_db),
    limit: int = 20,
) -> dict:
    """The sidebar list: threads that have something in them, newest use first.

    Blank threads are excluded in SQL rather than by the client, so `limit`
    counts real conversations. The opening line is fetched with a lateral join
    instead of a query per row: at 20 threads the old shape was 21 round trips
    to Neon, which is most of the sidebar's load time.
    """
    opener = (
        select(Message.content)
        .where(Message.conversation_id == Conversation.id, Message.role == "user")
        .order_by(Message.id)
        .limit(1)
        .scalar_subquery()
        .label("opener")
    )
    rows = await session.execute(
        select(Conversation, opener)
        .where(
            Conversation.user_id == user_id,
            select(Message.id)
            .where(Message.conversation_id == Conversation.id)
            .exists(),
        )
        .order_by(Conversation.updated_at.desc())
        .limit(min(limit, 50))
    )
    return {
        "items": [
            {
                "id": c.id,
                "title": c.title or (opening[:60] if opening else "New conversation"),
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
                "empty": False,
            }
            for c, opening in rows
        ]
    }


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_read_db),
) -> dict:
    row = await session.execute(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id
        )
    )
    if row.scalar_one_or_none() is None:
        raise NotFound("We could not find that conversation.")
    messages = await load_history(session, conversation_id)
    return {"id": conversation_id, "messages": messages}


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str,
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_db),
    _: None = Depends(verify_csrf),
) -> None:
    row = await session.execute(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id
        )
    )
    conversation = row.scalar_one_or_none()
    if conversation is None:
        raise NotFound("We could not find that conversation.")
    await session.delete(conversation)


# ------------------------------------------------------------------ profile
@router.get("/profile")
async def profile(
    user_id: str = Depends(current_user_id), session: AsyncSession = Depends(get_read_db)
) -> dict:
    user = await session.get(User, user_id)
    if user is None:
        raise NotFound()
    orders = await order_service.list_orders(session, user_id, limit=100)
    return {
        "user": auth_service.serialise_user(user),
        "stats": {
            "orders_placed": len(orders),
            "last_order_at": orders[0].confirmed_at.isoformat() if orders else None,
        },
    }


@router.get("/profile/memories")
async def memories(user_id: str = Depends(current_user_id)) -> dict:
    return await memory_service.list_memories(user_id)


@router.delete("/profile/memories/{memory_id}", status_code=204)
async def forget_memory(
    memory_id: str,
    user_id: str = Depends(current_user_id),
    _: None = Depends(verify_csrf),
) -> None:
    await memory_service.forget(user_id, memory_id)


@router.delete("/profile/memories", status_code=204)
async def forget_all_memories(
    user_id: str = Depends(current_user_id), _: None = Depends(verify_csrf)
) -> None:
    await memory_service.forget_all(user_id)
