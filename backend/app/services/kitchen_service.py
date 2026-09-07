"""The kitchen's view of its own orders.

Staff see one restaurant: the one on their account. That is the same ownership
rule the customer side runs on, one level up - every method here takes the
staff member's restaurant and filters by it, so there is no query that could
accidentally return another kitchen's work.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MenuItem, Order, OrderLine, Restaurant, User
from app.services import menu_service, money, order_service
from app.services.errors import NotFound, Unauthenticated

# What the kitchen is working on right now, in the order it needs attention.
LIVE_STATUSES = ["confirmed", "preparing", "ready", "out_for_delivery"]
QUEUE_ORDER = {s: i for i, s in enumerate(LIVE_STATUSES)}


async def require_staff(session: AsyncSession, user_id: str) -> User:
    """Staff-only, and only for their own kitchen."""
    user = await session.get(User, user_id)
    if user is None or user.status != "active":
        raise Unauthenticated()
    if user.role != "staff" or not user.staff_restaurant_id:
        # Not "forbidden": a customer has no business knowing this exists.
        raise NotFound()
    return user


async def restaurant_for(session: AsyncSession, user: User) -> Restaurant:
    restaurant = await session.get(Restaurant, user.staff_restaurant_id)
    if restaurant is None:
        raise NotFound()
    return restaurant


async def queue(session: AsyncSession, restaurant_id: str) -> list[dict[str, Any]]:
    """Live orders, oldest first within each stage."""
    rows = await session.execute(
        select(Order)
        .where(Order.restaurant_id == restaurant_id, Order.status.in_(LIVE_STATUSES))
        .order_by(Order.confirmed_at)
    )
    orders = sorted(rows.scalars(), key=lambda o: (QUEUE_ORDER.get(o.status, 9), o.confirmed_at))

    now = datetime.now(timezone.utc)
    out = []
    for order in orders:
        data = order_service.serialise(order)
        waited = now - order.confirmed_at
        data["waiting_minutes"] = int(waited.total_seconds() // 60)
        # A ticket that has sat past this is the one to look at first.
        data["is_late"] = waited > timedelta(minutes=25)
        data["next_statuses"] = sorted(order_service.TRANSITIONS.get(order.status, set()))
        out.append(data)
    return out


async def history(
    session: AsyncSession, restaurant_id: str, limit: int = 25
) -> list[dict[str, Any]]:
    rows = await session.execute(
        select(Order)
        .where(
            Order.restaurant_id == restaurant_id,
            Order.status.in_(["completed", "cancelled"]),
        )
        .order_by(Order.confirmed_at.desc())
        .limit(limit)
    )
    return [order_service.serialise(o) for o in rows.scalars()]


async def stats(session: AsyncSession, restaurant_id: str) -> dict[str, Any]:
    """Today's numbers. Money stays in minor units until it is displayed."""
    midnight = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    row = await session.execute(
        select(
            func.count(Order.id),
            func.coalesce(func.sum(Order.total), 0),
        ).where(
            Order.restaurant_id == restaurant_id,
            Order.confirmed_at >= midnight,
            Order.status != "cancelled",
        )
    )
    count, revenue = row.one()

    cancelled = await session.execute(
        select(func.count(Order.id)).where(
            Order.restaurant_id == restaurant_id,
            Order.confirmed_at >= midnight,
            Order.status == "cancelled",
        )
    )

    live = await session.execute(
        select(Order.status, func.count(Order.id))
        .where(Order.restaurant_id == restaurant_id, Order.status.in_(LIVE_STATUSES))
        .group_by(Order.status)
    )
    by_status = {s: 0 for s in LIVE_STATUSES}
    by_status.update({s: n for s, n in live})

    top = await session.execute(
        select(OrderLine.item_name, func.sum(OrderLine.quantity).label("n"))
        .join(Order, Order.id == OrderLine.order_id)
        .where(
            Order.restaurant_id == restaurant_id,
            Order.confirmed_at >= midnight,
            Order.status != "cancelled",
        )
        .group_by(OrderLine.item_name)
        .order_by(func.sum(OrderLine.quantity).desc())
        .limit(5)
    )

    return {
        "orders_today": count or 0,
        "cancelled_today": cancelled.scalar() or 0,
        **money.money_fields("revenue_today", int(revenue or 0)),
        "live_by_status": by_status,
        "top_items": [{"name": name, "quantity": int(n)} for name, n in top],
    }


async def advance(
    session: AsyncSession,
    restaurant_id: str,
    *,
    order_id: str,
    to_status: str,
    reason: str = "",
) -> dict[str, Any]:
    """Move a ticket along. Rule L1 still applies: illegal moves are refused."""
    row = await session.execute(
        select(Order).where(
            Order.id == order_id.strip().upper(), Order.restaurant_id == restaurant_id
        )
    )
    order = row.scalar_one_or_none()
    if order is None:
        raise NotFound("We could not find that order.")

    order = await order_service.transition(
        session, order, to_status=to_status, actor="staff", reason=reason[:200]
    )
    return order_service.serialise(order, include_events=True)


async def menu_board(session: AsyncSession, restaurant_id: str) -> list[dict[str, Any]]:
    """Every dish this kitchen owns, including the ones currently 86'd."""
    rows = await session.execute(
        select(MenuItem)
        .where(MenuItem.restaurant_id == restaurant_id, MenuItem.is_active.is_(True))
        .order_by(MenuItem.sort_order, MenuItem.name)
    )
    return [
        {
            "id": i.id,
            "name": i.name,
            "category": i.category,
            "is_available": i.is_available,
            **money.money_fields("price", i.base_price),
        }
        for i in rows.scalars()
    ]


async def set_availability(
    session: AsyncSession, restaurant_id: str, *, item_id: str, is_available: bool
) -> dict[str, Any]:
    """86 a dish, or bring it back.

    The cached menu is invalidated immediately: a dish taken off at the pass
    must stop being offered on the next turn, not up to a minute later.
    """
    item = await session.get(MenuItem, item_id.strip())
    if item is None or item.restaurant_id != restaurant_id:
        raise NotFound("That dish is not on your menu.")

    item.is_available = is_available
    await session.flush()
    menu_service.invalidate_cache()

    return {
        "id": item.id,
        "name": item.name,
        "is_available": item.is_available,
        **money.money_fields("price", item.base_price),
    }
