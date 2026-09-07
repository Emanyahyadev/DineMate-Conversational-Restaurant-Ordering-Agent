"""One turn, end to end (ARCHITECTURE.md section 3).

Assembles context, runs the agent, streams tokens, persists the turn, then
extracts memory off the critical path.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from agents import Runner
from agents.exceptions import MaxTurnsExceeded
from agents.stream_events import RawResponsesStreamEvent, RunItemStreamEvent
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.context import ChatContext
from app.agent.runtime import PROMPT_VERSION, build_agent, memory_extractor
from app.config import settings
from app.db.models import Conversation, Message
from app.db.postgres import SessionLocal
from app.services import cart_service, memory_extract, memory_service
from app.services.errors import NotFound

logger = logging.getLogger(__name__)

TOOL_LABELS = {
    "search_menu": "Checking the menu",
    "get_item_details": "Looking that up",
    "add_to_cart": "Adding to your order",
    "update_cart_item": "Updating your order",
    "remove_from_cart": "Updating your order",
    "view_cart": "Reviewing your order",
    "confirm_order": "Placing your order",
    "order_status": "Checking your order",
    "cancel_order": "Cancelling your order",
}

MAX_HISTORY_CHARS = 8000  # ~2000 tokens (ARCHITECTURE.md section 4)


async def ensure_conversation(
    session: AsyncSession, user_id: str, conversation_id: str | None
) -> Conversation:
    if conversation_id:
        row = await session.execute(
            select(Conversation).where(
                Conversation.id == conversation_id, Conversation.user_id == user_id
            )
        )
        found = row.scalar_one_or_none()
        if found is None:
            raise NotFound("We could not find that conversation.")
        return found

    conversation = Conversation(user_id=user_id)
    session.add(conversation)
    await session.flush()
    return conversation


async def load_history(session: AsyncSession, conversation_id: str) -> list[dict[str, str]]:
    """Last N turns, oldest first, truncated oldest-first to the char budget (Rule V3)."""
    rows = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.id.desc())
        .limit(settings.history_turns * 2)
    )
    messages = list(rows.scalars())[::-1]

    budget, kept = MAX_HISTORY_CHARS, []
    for m in reversed(messages):
        if budget - len(m.content) < 0:
            break
        kept.append({"role": m.role, "content": m.content})
        budget -= len(m.content)
    return kept[::-1]


def _sse(event: str, data: dict[str, Any]) -> dict[str, str]:
    return {"event": event, "data": json.dumps(data, default=str)}


async def run_turn_stream(
    *,
    user_id: str,
    message: str,
    conversation_id: str | None,
) -> AsyncIterator[dict[str, str]]:
    """Yields SSE events per API_CONTRACT.md section 4."""
    started = time.perf_counter()
    turn_id = uuid.uuid4().hex
    ttft_ms: float | None = None
    reply_parts: list[str] = []
    usage = {"prompt_tokens": 0, "completion_tokens": 0}
    degraded_memory = False

    async with SessionLocal() as session:
        try:
            conversation = await ensure_conversation(session, user_id, conversation_id)
            conv_id = conversation.id

            # Context assembly: memory and history read concurrently (P05, P03).
            memory_task = asyncio.create_task(memory_service.profile_summary(user_id))
            history = await load_history(session, conv_id)
            memory = await memory_task
            degraded_memory = memory.startswith("Nothing on file") and False

            await session.commit()
        except Exception as exc:
            logger.exception("context assembly failed")
            yield _sse("error", {"code": "STORAGE_UNAVAILABLE", "message": str(exc)})
            return

    # A dedicated session for the turn: tools write through it, and it commits once.
    async with SessionLocal() as session:
        ctx = ChatContext(user_id=user_id, session=session, turn_id=turn_id)
        yield _sse("start", {"conversation_id": conv_id, "turn_id": turn_id})

        try:
            agent = build_agent(memory)
            result = Runner.run_streamed(
                agent,
                [*history, {"role": "user", "content": message}],
                context=ctx,
                max_turns=settings.max_agent_turns,
            )

            async for event in result.stream_events():
                if isinstance(event, RawResponsesStreamEvent):
                    data = event.data
                    delta = getattr(data, "delta", None)
                    if getattr(data, "type", "") == "response.output_text.delta" and delta:
                        if ttft_ms is None:
                            ttft_ms = (time.perf_counter() - started) * 1000
                        reply_parts.append(delta)
                        yield _sse("token", {"delta": delta})

                elif isinstance(event, RunItemStreamEvent):
                    item = event.item
                    if event.name == "tool_called":
                        name = getattr(getattr(item, "raw_item", None), "name", "") or ""
                        yield _sse(
                            "tool",
                            {
                                "name": name,
                                "phase": "start",
                                "label": TOOL_LABELS.get(name, "Working on it"),
                            },
                        )
                    elif event.name == "tool_output":
                        name = getattr(getattr(item, "raw_item", None), "name", "") or ""
                        yield _sse("tool", {"name": name, "phase": "end", "label": ""})
                        if ctx.cart_snapshot is not None:
                            yield _sse("cart", {"cart": ctx.cart_snapshot})

            final = result.final_output if isinstance(result.final_output, str) else ""
            if final and not reply_parts:
                # Non-streaming model (the fake): emit the reply as one chunk.
                if ttft_ms is None:
                    ttft_ms = (time.perf_counter() - started) * 1000
                reply_parts.append(final)
                yield _sse("token", {"delta": final})

            for u in getattr(result, "raw_responses", []) or []:
                if getattr(u, "usage", None):
                    usage["prompt_tokens"] += u.usage.input_tokens or 0
                    usage["completion_tokens"] += u.usage.output_tokens or 0

            reply = "".join(reply_parts).strip() or (
                "Sorry, I did not catch that. Could you say it another way?"
            )

            session.add(Message(conversation_id=conv_id, role="user", content=message))
            session.add(
                Message(
                    conversation_id=conv_id,
                    role="assistant",
                    content=reply,
                    prompt_version=PROMPT_VERSION,
                    trace_id=turn_id,
                )
            )
            await session.commit()

        except MaxTurnsExceeded:
            # The model went round in circles. Say so rather than leaving the
            # customer watching a spinner forever (BC-7).
            await session.commit()
            logger.warning("agent exceeded %s turns", settings.max_agent_turns)
            yield _sse(
                "error",
                {
                    "code": "AGENT_STALLED",
                    "message": (
                        "Sorry, I got stuck on that one. Could you put it another way? "
                        "You can also pick a dish from the menu on the right."
                    ),
                },
            )
            return

        except Exception as exc:  # noqa: BLE001 - never fabricate a reply (BC-7)
            await session.rollback()
            logger.exception("agent turn failed")
            yield _sse(
                "error",
                {
                    "code": "LLM_UNAVAILABLE",
                    "message": "I cannot reach the kitchen's brain right now. Please try again.",
                    "detail": str(exc)[:200] if not settings.is_production else "",
                },
            )
            return

    duration_ms = (time.perf_counter() - started) * 1000
    yield _sse(
        "done",
        {
            "conversation_id": conv_id,
            "usage": usage,
            "duration_ms": round(duration_ms, 1),
            "ttft_ms": round(ttft_ms or duration_ms, 1),
            "tool_calls": [t["name"] for t in ctx.tool_calls],
            "degraded": {"memory": degraded_memory},
        },
    )

    # Two-stage memory. The rule pass is synchronous and always completes, so a
    # stated allergy is on file before the customer's next message. The model
    # pass is richer but is a second LLM call, so it runs detached and may not
    # land for a while on a slow provider.
    rules = memory_extract.extract(message)
    if rules["preferences"] or rules["facts"]:
        try:
            await memory_service.remember(user_id, rules["preferences"], rules["facts"])
        except Exception as exc:  # noqa: BLE001 - memory never breaks a chat
            logger.info("rule-based memory write skipped: %s", exc)

    _schedule_memory_extraction(user_id, message, "".join(reply_parts))


_BACKGROUND: set[asyncio.Task] = set()


def _schedule_memory_extraction(user_id: str, message: str, reply: str) -> None:
    """Fire and forget, but keep a strong reference so the task is not GC'd."""
    try:
        task = asyncio.create_task(_extract_memory_safely(user_id, message, reply))
    except RuntimeError:  # no running loop (shutdown)
        return
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)


async def _extract_memory_safely(user_id: str, user_message: str, reply: str) -> None:
    """Memory extraction must never break a chat."""
    try:
        turn = f"Customer: {user_message}\nAssistant: {reply}"
        result = await Runner.run(memory_extractor(), turn)
        raw = result.final_output
        if isinstance(raw, str):
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.strip("`").split("\n", 1)[-1]
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                return
        if not isinstance(raw, dict):
            return
        await memory_service.remember(
            user_id, raw.get("preferences", []) or [], raw.get("facts", []) or []
        )
    except (RuntimeError, asyncio.CancelledError):
        return  # loop torn down before extraction ran
    except Exception as exc:  # noqa: BLE001
        logger.info("memory extraction skipped: %s", exc)


async def confirmation_token_for(user_id: str) -> str | None:
    """The browser's 'Place order' button needs a token of its own (FRONTEND_SPEC 4)."""
    async with SessionLocal() as session:
        token = await cart_service.issue_confirmation_token(session, user_id)
        await session.commit()
        return token
