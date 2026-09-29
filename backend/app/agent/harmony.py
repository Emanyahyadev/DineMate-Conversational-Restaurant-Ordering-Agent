"""Repairing harmony-format leakage from gpt-oss models.

`openai/gpt-oss-*` speaks the "harmony" format internally: its output is split
into channels (`analysis`, `commentary`, `final`) delimited by control tokens
like ``<|channel|>`` and ``<|end|>``. The provider is supposed to parse those
away. On the NVIDIA endpoint it does not always manage it, and the tokens reach
us verbatim. Two things break as a result:

1. **Tool calls die.** The model names a tool ``view_cart<|channel|>commentary``
   and the SDK, quite correctly, reports that no such tool exists - the turn
   ends with ModelBehaviorError and the customer's dish is never added. This is
   the whole of "it finds the dish but never orders it".

2. **Replies flicker.** Raw ``<|channel|>commentary`` text streams into the
   chat bubble before the real answer arrives.

The right long-term fix is a model whose tool calling is reliable, but every
alternative on this endpoint currently times out (ADR-0006). So we repair the
stream instead: strip the control tokens, and cut a tool name at the first one.

This is deliberately narrow. It only removes ``<|...|>`` markers and what a
tool name cannot contain anyway - it never rewrites a name into a *different*
valid tool, so a genuinely wrong tool name still fails loudly.
"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from typing import Any

from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel

logger = logging.getLogger(__name__)

# ``<|channel|>``, ``<|end|>``, ``<|start|>``, ``<|constrain|>`` and friends.
CONTROL_TOKEN = re.compile(r"<\|[^|>]*\|>")

# A tool name is a plain identifier. Anything from the first character that
# cannot appear in one is leakage.
_NAME_TAIL = re.compile(r"[^A-Za-z0-9_].*$", re.DOTALL)


def clean_tool_name(name: str) -> str:
    """``"view_cart<|channel|>commentary"`` -> ``"view_cart"``."""
    if not name:
        return name
    cleaned = _NAME_TAIL.sub("", name.strip())
    if cleaned != name:
        logger.warning("repaired harmony-mangled tool name %r -> %r", name, cleaned)
    return cleaned


def strip_control_tokens(text: str) -> str:
    """Remove harmony control tokens from text meant for the customer."""
    return CONTROL_TOKEN.sub("", text) if text else text


def _repair_item(item: Any) -> None:
    """Fix a function-call item in place, if that is what it is."""
    if getattr(item, "type", None) != "function_call":
        return
    name = getattr(item, "name", None)
    if isinstance(name, str):
        cleaned = clean_tool_name(name)
        if cleaned != name:
            item.name = cleaned


def repair_event(event: Any) -> Any:
    """Repair one streamed event in place and hand it back.

    Tool names reach the run loop by two routes - the per-item events as they
    are added and completed, and the assembled response at the end - so both are
    swept. Missing one leaves the failure exactly as it was.
    """
    item = getattr(event, "item", None)
    if item is not None:
        _repair_item(item)

    response = getattr(event, "response", None)
    if response is not None:
        for output in getattr(response, "output", None) or []:
            _repair_item(output)

    # Text deltas: never show the customer a control token.
    delta = getattr(event, "delta", None)
    if isinstance(delta, str) and "<|" in delta:
        event.delta = strip_control_tokens(delta)

    return event


def repair_chunk(chunk: Any) -> Any:
    """Clean one raw ChatCompletionChunk in place.

    This is the earliest point the mangled name exists in our process. Repairing
    the SDK's *events* was not enough: it resolves a tool name from state it
    assembles out of these chunks, so by the time an event carries the name the
    lookup has already failed. Clean it here and everything downstream is right.
    """
    for choice in getattr(chunk, "choices", None) or []:
        delta = getattr(choice, "delta", None)
        if delta is None:
            continue
        for call in getattr(delta, "tool_calls", None) or []:
            fn = getattr(call, "function", None)
            name = getattr(fn, "name", None)
            if isinstance(name, str) and name:
                fn.name = clean_tool_name(name)
        content = getattr(delta, "content", None)
        if isinstance(content, str) and "<|" in content:
            delta.content = strip_control_tokens(content)
    return chunk


class HarmonySafeModel(OpenAIChatCompletionsModel):
    """The chat-completions model, with harmony leakage repaired on the way out.

    A subclass rather than a wrapper because the SDK type-checks the model it is
    given (``Agent model must be a string, Model, or None``), so a duck-typed
    proxy is rejected.

    Repair happens in two places on purpose. ``_fetch_response`` catches the raw
    chunks, which is what actually fixes tool resolution; the event and response
    sweeps below are a backstop for a marker split across a chunk boundary,
    where no single chunk looks wrong.
    """

    async def _fetch_response(self, *args: Any, **kwargs: Any) -> Any:
        result = await super()._fetch_response(*args, **kwargs)

        # Streaming returns (response, stream); non-streaming returns the
        # completion on its own.
        if isinstance(result, tuple) and len(result) == 2:
            response, stream = result

            async def cleaned() -> AsyncIterator[Any]:
                async for chunk in stream:
                    yield repair_chunk(chunk)

            return response, cleaned()

        for choice in getattr(result, "choices", None) or []:
            fn = getattr(getattr(choice, "message", None), "tool_calls", None) or []
            for call in fn:
                inner = getattr(call, "function", None)
                name = getattr(inner, "name", None)
                if isinstance(name, str) and name:
                    inner.name = clean_tool_name(name)
        return result

    async def get_response(self, *args: Any, **kwargs: Any) -> Any:
        response = await super().get_response(*args, **kwargs)
        for output in getattr(response, "output", None) or []:
            _repair_item(output)
        return response

    async def stream_response(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        async for event in super().stream_response(*args, **kwargs):
            yield repair_event(event)
