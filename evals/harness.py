"""Eval harness: runs golden cases against the agent and scores them.

Assertions are over tool calls and database state, never prose
(EVAL_PLAN.md section 1).
"""

from __future__ import annotations

import re
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.config import settings  # noqa: E402

settings.use_fake_llm = True
settings.testing = True

from agents import Runner  # noqa: E402
from sqlalchemy import delete, select, text  # noqa: E402

from app.agent.context import ChatContext  # noqa: E402
from app.agent.runtime import build_agent  # noqa: E402
from app.db.models import (  # noqa: E402
    Cart,
    ConfirmationToken,
    Conversation,
    MenuItem,
    Order,
    OrderEvent,
    OrderLine,
    User,
)
from app.db.postgres import SessionLocal  # noqa: E402
from app.services import cart_service, memory_service  # noqa: E402

CASES_DIR = Path(__file__).parent / "cases"

MONEY = re.compile(r"\$\d+\.\d{2}")


@dataclass
class TurnResult:
    user: str
    reply: str
    tools: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class CaseResult:
    case_id: str
    title: str
    us: list[str]
    kpi: list[str]
    passed: bool
    failures: list[str] = field(default_factory=list)
    turns: list[TurnResult] = field(default_factory=list)
    violations: set[str] = field(default_factory=set)


def load_cases(filter_: str | None = None) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in sorted(CASES_DIR.glob("*.yaml")):
        for case in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
            if filter_ and filter_.upper() not in case["id"].upper():
                continue
            cases.append(case)
    return cases


async def _reset_db() -> None:
    async with SessionLocal() as s:
        for model in (
            OrderEvent, OrderLine, Order, ConfirmationToken, Cart, Conversation, User,
        ):
            await s.execute(delete(model))
        await s.execute(text("UPDATE menu_items SET is_available = true, is_active = true"))
        await s.commit()
    from app.services import menu_service

    menu_service.invalidate_cache()


async def _default_options(session, item_id: str) -> list[str]:
    """Pick the first option of every mandatory group so fixtures satisfy Rule O1."""
    item = await session.get(MenuItem, item_id)
    if item is None:
        return []
    chosen: list[str] = []
    for group in item.option_groups:
        if group.min_select > 0 and group.options:
            chosen.append(sorted(group.options, key=lambda o: o.sort_order)[0].id)
    return chosen


async def _seed(case: dict[str, Any]) -> str:
    """Create the case's user and starting state; returns user_id."""
    seed = case.get("seed", {}) or {}
    async with SessionLocal() as s:
        user = User(
            email=f"{uuid.uuid4().hex[:10]}@eval.example",
            password_hash="x",
            status="active",
            display_name=seed.get("user", "eval"),
        )
        s.add(user)
        await s.flush()
        user_id = user.id

        for item_id in seed.get("unavailable", []) or []:
            item = await s.get(MenuItem, item_id)
            if item:
                item.is_available = False

        for line in seed.get("cart", []) or []:
            await cart_service.add_line(
                s,
                user_id,
                item_id=line["item_id"],
                quantity=line.get("quantity", 1),
                option_ids=line.get("option_ids")
                or await _default_options(s, line["item_id"]),
            )
        await s.commit()

    from app.services import menu_service

    menu_service.invalidate_cache()

    await memory_service.forget_all(user_id)
    mem = seed.get("memory", {}) or {}
    if mem:
        await memory_service.remember(
            user_id,
            [{"text": t, "confidence": 1.0} for t in mem.get("preferences", [])],
            [
                {"text": f["text"], "kind": f.get("kind", "other"), "confidence": 1.0}
                for f in mem.get("facts", [])
            ],
        )

    # Seed a prior order if the case needs one to inspect or cancel.
    if seed.get("order"):
        async with SessionLocal() as s:
            spec = seed["order"]
            for line in spec.get("lines", []):
                await cart_service.add_line(
                    s,
                    user_id,
                    item_id=line["item_id"],
                    quantity=line.get("quantity", 1),
                    option_ids=await _default_options(s, line["item_id"]),
                )
            token = await cart_service.issue_confirmation_token(s, user_id, turn_id="seed")
            await s.commit()
        async with SessionLocal() as s:
            from app.services import order_service

            # confirm() returns one order per kitchen; a seeded fixture is a
            # single kitchen, but the loop keeps it honest either way.
            orders = await order_service.confirm(
                s,
                user_id,
                confirmation_token=token,
                contact_phone="03001234567",
                idempotency_key=f"seed-{user_id}",
            )
            if spec.get("status") and spec["status"] != "confirmed":
                for created in orders:
                    row = await s.get(Order, created["id"])
                    await order_service.transition(
                        s, row, to_status=spec["status"], actor="staff"
                    )
            await s.commit()
    return user_id


async def _run_turns(case: dict[str, Any], user_id: str) -> list[TurnResult]:
    history: list[dict[str, str]] = []
    results: list[TurnResult] = []

    for turn in case["turns"]:
        async with SessionLocal() as s:
            ctx = ChatContext(user_id=user_id, session=s, turn_id=uuid.uuid4().hex)
            memory = await memory_service.profile_summary(user_id)
            agent = build_agent(memory)
            try:
                run = await Runner.run(
                    agent, [*history, {"role": "user", "content": turn["user"]}], context=ctx
                )
                reply = run.final_output if isinstance(run.final_output, str) else ""
            except Exception as exc:  # noqa: BLE001
                reply = f"[run error: {exc}]"
            await s.commit()

        history.append({"role": "user", "content": turn["user"]})
        history.append({"role": "assistant", "content": reply})
        results.append(
            TurnResult(
                user=turn["user"],
                reply=reply,
                tools=list(ctx.tool_calls),
                tool_results=list(ctx.tool_results),
            )
        )
    return results


# --------------------------------------------------------------------- scorers
def _names(turn: TurnResult) -> list[str]:
    return [t["name"] for t in turn.tools]


def _mentioned_items(reply: str, menu_names: list[str]) -> list[str]:
    low = reply.lower()
    return [n for n in menu_names if n.lower() in low]


def score_turn(
    turn: TurnResult, expect: dict[str, Any], menu_names: list[str]
) -> tuple[list[str], set[str]]:
    """Returns (failures, violated KPI ids)."""
    failures: list[str] = []
    violations: set[str] = set()
    names = _names(turn)

    for want in expect.get("tools", []) or []:
        if want["name"] not in names:
            failures.append(f"expected tool {want['name']}, got {names or 'none'}")
            violations.add("A04")
            continue
        call = next(t for t in turn.tools if t["name"] == want["name"])
        for key, value in (want.get("args") or {}).items():
            actual = call["args"].get(key)
            if actual != value:
                failures.append(
                    f"{want['name']}.{key} expected {value!r}, got {actual!r}"
                )
                violations.add("A05")

    for banned in expect.get("not_tools", []) or []:
        if banned in names:
            failures.append(f"tool {banned} must not be called here")
            violations.add("A01" if banned in ("confirm_order", "cancel_order") else "A04")

    for needle in expect.get("reply_contains", []) or []:
        if needle.lower() not in turn.reply.lower():
            failures.append(f"reply missing {needle!r}")

    for needle in expect.get("reply_excludes", []) or []:
        if needle.lower() in turn.reply.lower():
            failures.append(f"reply must not contain {needle!r}")
            violations.add("A03")

    # A02: every dish name and money string in the reply must come from a tool result.
    if expect.get("grounded", True):
        grounded_text = str(turn.tool_results)
        for name in _mentioned_items(turn.reply, menu_names):
            if name not in grounded_text:
                failures.append(f"ungrounded menu item {name!r} in reply")
                violations.add("A02")
        for amount in MONEY.findall(turn.reply):
            if amount not in grounded_text:
                failures.append(f"ungrounded price {amount} in reply")
                violations.add("A02")

    if expect.get("asks_question"):
        if "?" not in turn.reply:
            failures.append("expected a clarifying question")
            violations.add("A09")

    return failures, violations


async def _check_final(case: dict[str, Any], user_id: str) -> tuple[list[str], set[str]]:
    failures: list[str] = []
    violations: set[str] = set()
    expect = case.get("assert_final", {}) or {}

    async with SessionLocal() as s:
        cart = await cart_service.view(s, user_id)
        rows = await s.execute(select(Order).where(Order.user_id == user_id))
        orders = list(rows.scalars())

    if "cart_lines" in expect:
        want = {(l["item_id"], l["quantity"]) for l in expect["cart_lines"]}
        got = {(l["item_id"], l["quantity"]) for l in cart["lines"]}
        if want != got:
            failures.append(f"cart expected {sorted(want)}, got {sorted(got)}")
            violations.add("A05")

    if "orders_created" in expect:
        created = [
            o
            for o in orders
            if not (o.idempotency_key or "").startswith(f"seed-{user_id}")
        ]
        if len(created) != expect["orders_created"]:
            failures.append(
                f"expected {expect['orders_created']} new order(s), got {len(created)}"
            )
            violations.add("A01" if expect["orders_created"] == 0 else "A06")

    if "order_status" in expect:
        statuses = [o.status for o in orders]
        if expect["order_status"] not in statuses:
            failures.append(f"expected an order with status {expect['order_status']}, got {statuses}")
            violations.add("A06")

    if "memories_added" in expect:
        mem = await memory_service.list_memories(user_id)
        total = len(mem["preferences"]) + len(mem["facts"])
        seeded = case.get("seed", {}).get("memory", {}) or {}
        base = len(seeded.get("preferences", [])) + len(seeded.get("facts", []))
        if total - base != expect["memories_added"]:
            failures.append(
                f"expected {expect['memories_added']} new memories, got {total - base}"
            )
            violations.add("A08a")

    return failures, violations


async def run_case(case: dict[str, Any], menu_names: list[str]) -> CaseResult:
    await _reset_db()
    user_id = await _seed(case)
    turns = await _run_turns(case, user_id)

    failures: list[str] = []
    violations: set[str] = set()
    for turn, spec in zip(turns, case["turns"]):
        f, v = score_turn(turn, spec.get("expect", {}) or {}, menu_names)
        failures += [f"turn {turns.index(turn) + 1}: {x}" for x in f]
        violations |= v

    f, v = await _check_final(case, user_id)
    failures += f
    violations |= v

    return CaseResult(
        case_id=case["id"],
        title=case.get("title", ""),
        us=case.get("us", []),
        kpi=case.get("kpi", []),
        passed=not failures,
        failures=failures,
        turns=turns,
        violations=violations,
    )


async def menu_names() -> list[str]:
    async with SessionLocal() as s:
        rows = await s.execute(select(MenuItem.name))
        return [r[0] for r in rows]
