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
from datetime import UTC, datetime
from typing import Any

from agents import Runner
from agents.exceptions import MaxTurnsExceeded
from agents.stream_events import RawResponsesStreamEvent, RunItemStreamEvent
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.context import ChatContext
from app.agent.harmony import strip_control_tokens
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

# How many times a turn may be re-run after the provider breaks the stream.
#
# Two, not one. This endpoint's own harmony parser fails outright on a minority
# of completions ("unexpected tokens remaining in message header") - nothing we
# send is wrong and nothing we can clean helps, the response is simply spoiled.
# A second retry turns most of those into an answer. It is bounded because a
# customer would rather be told than watch a fourth attempt.
RETRY_ATTEMPTS = 2

# Tools that change something. A turn that has called one of these can never be
# retried: running it again would add the dish, or place the order, twice.
MUTATING_TOOLS = frozenset(
    {
        "add_to_cart",
        "update_cart_item",
        "remove_from_cart",
        "clear_cart",
        "confirm_order",
        "cancel_order",
    }
)


def _is_retryable(reply_parts: list[str], *, rolled_back: bool) -> bool:
    """Whether this turn can safely be run again from the top.

    About consequences, not about which exception it is. Two conditions:

    * **Nothing shown yet.** A retry produces a fresh reply; if part of one has
      already streamed, the customer would see two answers stitched together.
    * **The turn's writes are gone.** No service commits - `cart_service` and
      `order_service` write through the caller's session and the orchestrator is
      the only thing that commits - so a rolled-back attempt has left nothing
      behind and a second run cannot add the dish twice. `confirm_order` is
      further protected by its `turn-{turn_id}` idempotency key, which is stable
      across attempts, so even a committed order would be returned rather than
      duplicated.

    This is why a failure *after* add_to_cart is still retryable, which matters:
    it is the common case, since a multi-dish order spends most of its time
    mid-way through the adds.
    """
    if reply_parts:
        return False
    return rolled_back


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

    yield _sse("start", {"conversation_id": conv_id, "turn_id": turn_id})

    # A dedicated session per attempt: tools write through it, and it commits
    # once. A retry gets a fresh session and a fresh context, so a half-finished
    # attempt cannot leave anything behind for the next one to trip over.
    for attempt in range(RETRY_ATTEMPTS + 1):
        retry = False
        reply_parts = []
        async with SessionLocal() as session:
            ctx = ChatContext(user_id=user_id, session=session, turn_id=turn_id)

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
                            # Belt and braces with HarmonySafeModel: a control
                            # token must never reach the chat bubble, whatever
                            # route the delta arrived by.
                            delta = strip_control_tokens(delta)
                            if not delta:
                                continue
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

                # An empty completion is a failed turn even though nothing
                # raised: this provider sometimes returns tool calls and then no
                # text at all, which reached the customer as "Sorry, I did not
                # catch that" over a request that was perfectly clear. Treat it
                # like a broken stream and run the turn again, under exactly the
                # same safety rule - only when nothing has been changed for them.
                empty = not "".join(reply_parts).strip()
                if (
                    empty
                    and attempt < RETRY_ATTEMPTS
                    and _is_retryable(reply_parts, rolled_back=True)
                ):
                    logger.warning(
                        "empty completion, retrying turn (attempt %s)", attempt + 1
                    )
                    await session.rollback()
                    retry = True
                    continue

                reply = "".join(reply_parts).strip()
                if not reply:
                    # Out of retries with nothing said. What the tools did still
                    # stands, so say which of the two happened rather than
                    # blaming the customer's perfectly clear message for both.
                    changed = any(
                        call["name"] in MUTATING_TOOLS for call in ctx.tool_calls
                    )
                    if changed and ctx.cart_snapshot:
                        yield _sse("cart", {"cart": ctx.cart_snapshot})
                        reply = (
                            "I have updated your order — it is in the panel. "
                            "Tell me if that is not what you wanted."
                        )
                    else:
                        reply = (
                            "Sorry, I lost my train of thought there. "
                            "Could you say that again?"
                        )
                    yield _sse("token", {"delta": reply})

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
                # The thread is named by what the customer opened with, and stamped
                # every turn so the sidebar can order by "recently used" rather than
                # by when the thread happened to be created.
                #
                # Written as an UPDATE rather than through `conversation`: that
                # instance belongs to the context-assembly session above, which has
                # already closed, so assigning to it would persist nothing.
                await session.execute(
                    update(Conversation)
                    .where(Conversation.id == conv_id)
                    .values(
                        title=func.coalesce(Conversation.title, message.strip()[:80]),
                        updated_at=datetime.now(UTC),
                    )
                )
                await session.commit()

            except MaxTurnsExceeded:
                # The model ran out of turns. Say so rather than leaving the
                # customer watching a spinner forever (BC-7).
                #
                # Crucially, the work already done still stands: the tools ran
                # inside this transaction and their effects are real. Reporting a
                # flat failure over a cart that was correctly filled is a lie the
                # customer can see through the moment they look at the panel, so
                # commit and tell them what actually happened.
                await session.commit()
                logger.warning("agent exceeded %s turns", settings.max_agent_turns)

                added = [
                    call for call in ctx.tool_calls if call["name"] in MUTATING_TOOLS
                ]
                if added and ctx.cart_snapshot:
                    yield _sse("cart", {"cart": ctx.cart_snapshot})
                    message = (
                        "I took longer than I should have on that one, but your "
                        "order is updated - have a look at the panel and tell me "
                        "if it is right."
                    )
                else:
                    message = (
                        "Sorry, I got stuck on that one. Could you put it another "
                        "way? You can also pick a dish from the menu on the right."
                    )
                yield _sse("error", {"code": "AGENT_STALLED", "message": message})
                return

            except Exception as exc:
                await session.rollback()
                logger.exception("agent turn failed")

                # A provider that breaks the stream part-way is the single most
                # common failure here, and it is usually transient - the same turn
                # sent again succeeds. Retrying is only safe when nothing has
                # happened yet: no text shown to the customer (a retry would
                # duplicate it) and no tool that changed anything (add_to_cart is
                # not idempotent, so a retry would order the dish twice).
                # `session.rollback()` above undid everything this attempt
                # wrote, which is what makes another run safe.
                if attempt < RETRY_ATTEMPTS and _is_retryable(
                    reply_parts, rolled_back=True
                ):
                    logger.warning(
                        "retrying turn after a broken stream (attempt %s): %s",
                        attempt + 1,
                        str(exc)[:200],
                    )
                    retry = True
                else:
                    yield _sse(
                        "error",
                        {
                            "code": "LLM_UNAVAILABLE",
                            "message": (
                                "I cannot reach the kitchen's brain right now. "
                                "Please try again."
                            ),
                            "detail": str(exc)[:200] if not settings.is_production else "",
                        },
                    )
                    return

        if not retry:
            break

    # Memory is written BEFORE the terminal event. Anything placed after the
    # final yield of an async generator runs only if the consumer keeps
    # iterating past it - a client that stops at `done`, or a browser that
    # navigates away, silently discarded it.
    reply_text = "".join(reply_parts)
    rules = memory_extract.extract(message)
    memories_written = 0
    if rules["preferences"] or rules["facts"]:
        try:
            memories_written = await memory_service.remember(
                user_id, rules["preferences"], rules["facts"]
            )
        except Exception as exc:
            logger.info("rule-based memory write skipped: %s", exc)

    # The model pass is richer but costs another call, so it stays detached.
    _schedule_memory_extraction(user_id, message, reply_text)

    duration_ms = (time.perf_counter() - started) * 1000
    yield _sse(
        "done",
        {
            "conversation_id": conv_id,
            "usage": usage,
            "duration_ms": round(duration_ms, 1),
            "ttft_ms": round(ttft_ms or duration_ms, 1),
            "tool_calls": [t["name"] for t in ctx.tool_calls],
            "memories_written": memories_written,
            "degraded": {"memory": degraded_memory},
        },
    )


# --------------------------------------------------------------- memory pass
_BACKGROUND: set[asyncio.Task] = set()


def _schedule_memory_extraction(user_id: str, message: str, reply: str) -> None:
    """Fire and forget, holding a strong reference so the task is not GC'd."""
    try:
        task = asyncio.create_task(_extract_memory_safely(user_id, message, reply))
    except RuntimeError:  # no running loop (shutdown)
        return
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)


async def _extract_memory_safely(user_id: str, user_message: str, reply: str) -> None:
    """The richer, model-based pass. Its failure must never surface: the rule
    pass has already stored whatever was stated outright."""
    try:
        turn = f"Customer: {user_message}\nAssistant: {reply}"
        result = await Runner.run(memory_extractor(), turn, max_turns=2)
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
        preferences = _corroborated(
            raw.get("preferences", []) or [], user_message, kind="preference"
        )
        facts = _corroborated(raw.get("facts", []) or [], user_message, kind="fact")
        await memory_service.remember(user_id, preferences, facts)
    except (RuntimeError, asyncio.CancelledError):
        return  # loop torn down before extraction ran
    except Exception as exc:
        logger.info("model memory extraction skipped: %s", exc)


# Memory that constrains what the customer is ever offered again. A wrong entry
# here is worse than none: it silently removes food from every future
# suggestion, and the customer is never told why.
BINDING_WORDS = (
    "vegetarian",
    "vegan",
    "pescatarian",
    "halal",
    "kosher",
    "gluten",
    "dairy",
    "allerg",
    "does not eat",
    "doesn't eat",
    "cannot eat",
    "avoids",
)


def _corroborated(
    entries: list[dict[str, Any]], message: str, *, kind: str
) -> list[dict[str, Any]]:
    """Drop model-extracted memories that bind future behaviour but were never
    actually declared.

    The model infers a standing diet from a passing request: "show me something
    vegetarian" became a permanent "Vegetarian" preference, after which the
    agent refused to add a chicken karahi and would not say why. Browsing a
    category is not a declaration.

    So anything dietary has to be corroborated by the deterministic rules in
    ``memory_extract``, which only fire on an outright statement ("I am
    vegetarian", "I am allergic to peanuts"). Everything else the model finds -
    a favourite dish, spice tolerance, a preferred name - is low-stakes and
    passes through, since being wrong there costs a suggestion, not a meal.
    """
    rules = memory_extract.extract(message)
    supported = " ".join(
        e["text"].lower()
        for e in (*rules["preferences"], *rules["facts"])
        if e.get("text")
    )

    kept: list[dict[str, Any]] = []
    for entry in entries:
        text_ = str(entry.get("text") or "").lower()
        if not text_:
            continue
        binding = any(word in text_ for word in BINDING_WORDS)
        if binding and not any(word in supported for word in BINDING_WORDS):
            logger.info(
                "dropped uncorroborated %s memory %r - not declared in %r",
                kind,
                entry.get("text"),
                message[:60],
            )
            continue
        kept.append(entry)
    return kept


async def confirmation_token_for(user_id: str) -> str | None:
    """The browser's Place order button needs a token of its own (FRONTEND_SPEC 4)."""
    async with SessionLocal() as session:
        token = await cart_service.issue_confirmation_token(session, user_id)
        await session.commit()
        return token
