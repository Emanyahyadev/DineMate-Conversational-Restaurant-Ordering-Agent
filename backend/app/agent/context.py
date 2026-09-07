"""The trusted per-turn context.

``user_id`` reaches tools only through here. No tool takes it as a parameter,
so the model has no channel to express another customer (AUTH_SPEC.md section 5,
KPI A03).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class ChatContext:
    user_id: str
    session: AsyncSession
    turn_id: str

    # Set by view_cart, read by confirm_order. Never visible to the model (ADR-0004).
    confirmation_token: str | None = None
    token_issued_this_turn: bool = False

    # Telemetry for the turn.
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    cart_snapshot: dict[str, Any] | None = None
    tool_results: list[dict[str, Any]] = field(default_factory=list)

    def record(self, name: str, args: dict[str, Any], result: Any) -> None:
        self.tool_calls.append({"name": name, "args": args})
        self.tool_results.append({"name": name, "result": result})
