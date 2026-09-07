"""Order confirmation, state machine and cancellation.

The confirm path is one atomic transaction (Rule R1) and is the only way an
order can come into existence (INV-8).
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import (
    Cart,
    ConfirmationToken,
    MenuItem,
    Order,
    OrderEvent,
    OrderLine,
)
from app.services import cart_service, money
from app.services.errors import (
    CancellationWindowExpired,
    CartChanged,
    CartEmpty,
    InvalidTransition,
    ItemUnavailable,
    NoConfirmation,
    OrderNotCancellable,
    OrderNotFound,
)

# DOMAIN_MODEL.md section 2 - Rule L1: only these transitions exist.
TRANSITIONS: dict[str, set[str]] = {
    "confirmed": {"preparing", "cancelled"},
    "preparing": {"ready", "cancelled"},
    "ready": {"out_for_delivery", "completed"},
    "out_for_delivery": {"completed"},
    "completed": set(),
    "cancelled": set(),
}

ETA_MINUTES = {"pickup": 20, "delivery": 35}


def _new_order_id() -> str:
    """Rule R3: speakable, non-sequential - a sequential id would let one
    customer guess another's."""
    return f"ORD-{random.SystemRandom().randint(100000, 999999)}"


def serialise(order: Order, *, include_events: bool = False) -> dict[str, Any]:
    cancellable_until = order.confirmed_at + timedelta(
        minutes=settings.cancellation_window_minutes
    )
    data: dict[str, Any] = {
        "id": order.id,
        "restaurant_id": order.restaurant_id,
        "restaurant_name": order.restaurant_name,
        "status": order.status,
        "fulfilment": order.fulfilment,
        "payment_method": order.payment_method,
        "notes": order.notes,
        "lines": [
            {
                "item_id": l.menu_item_id,
                "name": l.item_name,
                "quantity": l.quantity,
                "options": l.options_json,
                "note": l.note,
                **money.money_fields("unit_price", l.unit_price),
                **money.money_fields("line_total", l.line_total),
            }
            for l in order.lines
        ],
        **money.money_fields("subtotal", order.subtotal),
        **money.money_fields("tax", order.tax),
        **money.money_fields("delivery_fee", order.delivery_fee),
        **money.money_fields("total", order.total),
        "confirmed_at": order.confirmed_at.isoformat(),
        "cancellable_until": cancellable_until.isoformat(),
        "eta_minutes": ETA_MINUTES.get(order.fulfilment, 25),
    }
    if include_events:
        data["events"] = [
            {
                "from_status": e.from_status,
                "to_status": e.to_status,
                "actor": e.actor,
                "reason": e.reason,
                "created_at": e.created_at.isoformat(),
            }
            for e in sorted(order.events, key=lambda e: e.id)
        ]
    return data


async def confirm(
    session: AsyncSession,
    user_id: str,
    *,
    confirmation_token: str | None,
    fulfilment: str = "pickup",
    notes: str = "",
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Rule R1 - atomic. Validates the token, snapshots prices, writes the
    order, clears the cart and consumes the token, or does none of it."""

    # Idempotency: a retried confirm returns the original order (KPI R05).
    if idempotency_key:
        existing = await session.execute(
            select(Order).where(
                Order.idempotency_key == idempotency_key, Order.user_id == user_id
            )
        )
        prior = existing.scalar_one_or_none()
        if prior is not None:
            return serialise(prior)

    if not confirmation_token:
        raise NoConfirmation()

    row = await session.execute(
        select(ConfirmationToken)
        .where(ConfirmationToken.token == confirmation_token)
        .with_for_update()
    )
    token = row.scalar_one_or_none()
    now = datetime.now(timezone.utc)

    if token is None or token.user_id != user_id:
        raise NoConfirmation()
    if token.consumed_at is not None:
        raise NoConfirmation("That confirmation was already used.")
    if token.expires_at <= now:
        raise NoConfirmation("That confirmation expired. Let me read the order back again.")

    cart = await session.get(Cart, token.cart_id)
    if cart is None or cart.status != "open":
        raise CartChanged()
    if cart.version != token.cart_version:  # US-15
        raise CartChanged(cart_version=cart.version)
    if not cart.lines:
        raise CartEmpty()

    cart_data = await cart_service.serialise(session, cart)

    # Re-check availability at confirm time (Rule C3)
    for line in cart.lines:
        item = await session.get(MenuItem, line.menu_item_id)
        if item is None or not item.is_available or not item.is_active:
            raise ItemUnavailable(
                f"{item.name if item else line.menu_item_id} just became unavailable.",
                item_id=line.menu_item_id,
            )

    sub = cart_data["subtotal_cents"]
    tax = cart_data["tax_cents"]
    fee = 0
    order = Order(
        id=_new_order_id(),
        user_id=user_id,
        restaurant_id=cart.restaurant_id,
        restaurant_name=cart_data.get("restaurant_name") or "",
        status="confirmed",
        fulfilment=fulfilment if fulfilment in ("pickup", "delivery") else "pickup",
        subtotal=sub,
        tax=tax,
        delivery_fee=fee,
        total=money.order_total(sub, tax, fee),
        notes=notes[:500],
        idempotency_key=idempotency_key,
        confirmed_at=now,
    )
    session.add(order)
    await session.flush()

    for line in cart_data["lines"]:  # Rule R2 - price snapshots
        session.add(
            OrderLine(
                order_id=order.id,
                menu_item_id=line["item_id"],
                item_name=line["name"],
                unit_price=line["unit_price_cents"],
                quantity=line["quantity"],
                line_total=line["line_total_cents"],
                options_json=line["options"],
                note=line["note"],
            )
        )

    session.add(
        OrderEvent(  # INV-6
            order_id=order.id,
            from_status=None,
            to_status="confirmed",
            actor="customer",
            reason="confirmed in conversation",
        )
    )

    token.consumed_at = now
    cart.status = "confirmed"
    await session.flush()
    await session.refresh(order)
    return serialise(order)


async def get_order(session: AsyncSession, user_id: str, order_id: str) -> Order:
    """Owner-filtered. A foreign id is NOT_FOUND, never FORBIDDEN (US-18)."""
    row = await session.execute(
        select(Order).where(Order.id == order_id.strip().upper(), Order.user_id == user_id)
    )
    order = row.scalar_one_or_none()
    if order is None:
        raise OrderNotFound()
    return order


async def latest_open_order(session: AsyncSession, user_id: str) -> Order | None:
    row = await session.execute(
        select(Order)
        .where(
            Order.user_id == user_id,
            Order.status.in_(["confirmed", "preparing", "ready", "out_for_delivery"]),
        )
        .order_by(Order.confirmed_at.desc())
        .limit(1)
    )
    return row.scalar_one_or_none()


async def list_orders(session: AsyncSession, user_id: str, limit: int = 20) -> list[Order]:
    row = await session.execute(
        select(Order)
        .where(Order.user_id == user_id)
        .order_by(Order.confirmed_at.desc())
        .limit(limit)
    )
    return list(row.scalars())


async def transition(
    session: AsyncSession,
    order: Order,
    *,
    to_status: str,
    actor: str,
    reason: str = "",
) -> Order:
    """Rule L1/L5 - legal transitions only, always with an event."""
    if to_status not in TRANSITIONS.get(order.status, set()):
        raise InvalidTransition(f"Cannot move an order from {order.status} to {to_status}.")

    session.add(
        OrderEvent(
            order_id=order.id,
            from_status=order.status,
            to_status=to_status,
            actor=actor,
            reason=reason,
        )
    )
    order.status = to_status
    if to_status == "cancelled":
        order.cancelled_at = datetime.now(timezone.utc)
    await session.flush()
    await session.refresh(order)
    return order


async def cancel(
    session: AsyncSession, user_id: str, *, order_id: str, reason: str = ""
) -> dict[str, Any]:
    """Rules L2/L3 - customers may cancel only while confirmed and inside the window."""
    order = await get_order(session, user_id, order_id)

    if order.status != "confirmed":
        if order.status in ("preparing", "ready", "out_for_delivery"):
            raise CancellationWindowExpired()
        raise OrderNotCancellable(f"That order is already {order.status}.")

    deadline = order.confirmed_at + timedelta(minutes=settings.cancellation_window_minutes)
    if datetime.now(timezone.utc) >= deadline:
        raise CancellationWindowExpired()

    order = await transition(
        session, order, to_status="cancelled", actor="customer", reason=reason[:200]
    )
    return serialise(order)
