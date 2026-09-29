"""Order confirmation, state machine and cancellation.

The confirm path is one atomic transaction (Rule R1) and is the only way an
order can come into existence (INV-8).
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta
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
    User,
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
    ValidationError,
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
        "order_group_id": order.order_group_id,
        "restaurant_id": order.restaurant_id,
        "restaurant_name": order.restaurant_name,
        "status": order.status,
        "fulfilment": order.fulfilment,
        "payment_method": order.payment_method,
        "contact_phone": order.contact_phone,
        "delivery_address": order.delivery_address,
        "notes": order.notes,
        "lines": [
            {
                "item_id": ln.menu_item_id,
                "name": ln.item_name,
                "quantity": ln.quantity,
                "options": ln.options_json,
                "note": ln.note,
                **money.money_fields("unit_price", ln.unit_price),
                **money.money_fields("line_total", ln.line_total),
            }
            for ln in order.lines
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


async def contact_on_file(session: AsyncSession, user_id: str) -> dict[str, str]:
    """The delivery details we already hold for this customer.

    Kept in Postgres on the account rather than in the memory profile: it is
    contact PII, which AGENT_SPEC section 6 keeps out of the free-form memory
    documents, and it has to be deletable with the account in one transaction.
    """
    customer = await session.get(User, user_id)
    if customer is None:
        return {"phone": "", "address": ""}
    return {
        "phone": (customer.phone or "").strip(),
        "address": (customer.default_address or "").strip(),
    }


async def confirm(
    session: AsyncSession,
    user_id: str,
    *,
    confirmation_token: str | None,
    fulfilment: str = "pickup",
    notes: str = "",
    contact_phone: str = "",
    delivery_address: str = "",
    idempotency_key: str | None = None,
) -> list[dict[str, Any]]:
    """Rule R1 - atomic. Validates the token, snapshots prices, writes the
    order(s), clears the cart and consumes the token, or does none of it.

    A basket may span kitchens, and each kitchen cooks and dispatches on its own
    clock: one row cannot be "preparing" at Sindhi Biryani Co and "ready" at
    Chai Khana. So the basket splits into one order per kitchen, tied together
    by ``order_group_id`` for the customer's benefit. Every order is still a
    complete, independently cancellable record (INV-4 to INV-8).

    Returns the orders in menu order, always a list - even for one kitchen.
    """
    if idempotency_key:
        existing = await session.execute(
            select(Order)
            .where(Order.user_id == user_id)
            .where(Order.idempotency_key.like(f"{idempotency_key}%"))
        )
        prior = list(existing.scalars())
        if prior:
            return [serialise(o) for o in prior]

    if not confirmation_token:
        raise NoConfirmation()

    row = await session.execute(
        select(ConfirmationToken)
        .where(ConfirmationToken.token == confirmation_token)
        .with_for_update()
    )
    token = row.scalar_one_or_none()
    now = datetime.now(UTC)

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

    fulfilment = fulfilment if fulfilment in ("pickup", "delivery") else "pickup"
    phone = contact_phone.strip()[:32]
    address = delivery_address.strip()[:400]

    # What we already hold stands in for what was not supplied, so a returning
    # customer is asked to confirm rather than to type it all again (Rule N1).
    # Anything supplied wins: this is a fallback, never an override.
    customer = await session.get(User, user_id)
    if customer is not None:
        phone = phone or (customer.phone or "").strip()
        if fulfilment == "delivery":
            address = address or (customer.default_address or "").strip()

    if not phone:
        raise ValidationError("We need a phone number in case the kitchen has to call.")
    if fulfilment == "delivery" and not address:
        raise ValidationError("We need an address to deliver to.")

    # ...and today's details become the ones we hold for next time.
    if customer is not None:
        customer.phone = phone
        if address:
            customer.default_address = address

    group_id = str(uuid.uuid4())
    created: list[Order] = []

    for index, group in enumerate(cart_data["restaurants"]):
        sub = group["subtotal_cents"]
        tax = money.tax_for(sub)
        # Charged per kitchen: each sends its own rider.
        fee = settings.delivery_fee if fulfilment == "delivery" else 0
        order = Order(
            id=_new_order_id(),
            user_id=user_id,
            restaurant_id=group["restaurant_id"],
            restaurant_name=group["restaurant_name"],
            order_group_id=group_id,
            status="confirmed",
            fulfilment=fulfilment,
            contact_phone=phone,
            delivery_address=address if fulfilment == "delivery" else "",
            subtotal=sub,
            tax=tax,
            delivery_fee=fee,
            total=money.order_total(sub, tax, fee),
            notes=notes[:500],
            # Suffixed so a replayed checkout matches every order it created.
            idempotency_key=f"{idempotency_key}:{index}" if idempotency_key else None,
            confirmed_at=now,
        )
        session.add(order)
        await session.flush()

        for line in group["lines"]:  # Rule R2 - price snapshots
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
        created.append(order)

    token.consumed_at = now
    cart.status = "confirmed"
    await session.flush()
    for order in created:
        await session.refresh(order)
    return [serialise(o) for o in created]


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
        order.cancelled_at = datetime.now(UTC)
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
    if datetime.now(UTC) >= deadline:
        raise CancellationWindowExpired()

    order = await transition(
        session, order, to_status="cancelled", actor="customer", reason=reason[:200]
    )
    return serialise(order)
