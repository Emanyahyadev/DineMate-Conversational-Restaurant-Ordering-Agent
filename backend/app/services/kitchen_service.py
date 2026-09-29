"""The kitchen's view of its own orders.

Staff see one restaurant: the one on their account. That is the same ownership
rule the customer side runs on, one level up - every method here takes the
staff member's restaurant and filters by it, so there is no query that could
accidentally return another kitchen's work.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from app.db.models import MenuItem, Order, OrderLine, Restaurant, User
from app.services import menu_service, money, order_service
from app.services.errors import Conflict, NotFound, Unauthenticated, ValidationError

# What the kitchen is working on right now, in the order it needs attention.
LIVE_STATUSES = ["confirmed", "preparing", "ready", "out_for_delivery"]
QUEUE_ORDER = {s: i for i, s in enumerate(LIVE_STATUSES)}

#: A dish and nothing hanging off it. MenuItem.restaurant and
#: MenuItem.option_groups are both selectin by default, and the restaurant then
#: pulls its entire menu back through Restaurant.items - so reading this
#: kitchen's board costs four statements instead of one. None of it is used by
#: _serialise_item, and on a database in another region each statement is a
#: round trip somebody is waiting on.
_JUST_THE_DISH = (noload(MenuItem.restaurant), noload(MenuItem.option_groups))


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
    # Only the name and cuisine are wanted. Restaurant.items is selectin, so
    # without this the header of the dashboard fetches the entire menu, every
    # dish's option groups and every group's options - four statements to read
    # two strings, and the slowest call on the whole page.
    restaurant = await session.get(
        Restaurant, user.staff_restaurant_id, options=(noload(Restaurant.items),)
    )
    if restaurant is None:
        raise NotFound()
    return restaurant


def _ticket(
    order: Order, now: datetime, *, include_events: bool = False
) -> dict[str, Any]:
    """One order as the pass sees it: how long it has waited, and where next.

    Shared by `queue` and `advance` so a board that has just moved a ticket can
    swap that one row for the response, rather than re-reading the whole shift.
    """
    data = order_service.serialise(order, include_events=include_events)
    waited = now - order.confirmed_at
    data["waiting_minutes"] = int(waited.total_seconds() // 60)
    # A ticket that has sat past this is the one to look at first.
    data["is_late"] = waited > timedelta(minutes=25)
    data["next_statuses"] = sorted(order_service.TRANSITIONS.get(order.status, set()))
    return data


async def queue(session: AsyncSession, restaurant_id: str) -> list[dict[str, Any]]:
    """Live orders, oldest first within each stage."""
    rows = await session.execute(
        select(Order)
        .where(Order.restaurant_id == restaurant_id, Order.status.in_(LIVE_STATUSES))
        # Order.events is selectin-loaded by default; the board never shows an
        # audit trail, so that is a whole extra query on every 10-second poll.
        .options(noload(Order.events))
        .order_by(Order.confirmed_at)
    )
    orders = sorted(rows.scalars(), key=lambda o: (QUEUE_ORDER.get(o.status, 9), o.confirmed_at))

    now = datetime.now(UTC)
    return [_ticket(order, now) for order in orders]


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
    midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)

    # Placed, taken and cancelled in one pass over today's rows. Three separate
    # aggregates over the same window cost three round trips to a remote
    # Postgres, which is the whole of the dashboard's first-load delay.
    live_order = Order.status != "cancelled"
    row = await session.execute(
        select(
            func.coalesce(func.sum(case((live_order, 1), else_=0)), 0),
            func.coalesce(func.sum(case((live_order, Order.total), else_=0)), 0),
            func.coalesce(func.sum(case((Order.status == "cancelled", 1), else_=0)), 0),
        ).where(
            Order.restaurant_id == restaurant_id,
            Order.confirmed_at >= midnight,
        )
    )
    count, revenue, cancelled = row.one()

    live = await session.execute(
        select(Order.status, func.count(Order.id))
        .where(Order.restaurant_id == restaurant_id, Order.status.in_(LIVE_STATUSES))
        .group_by(Order.status)
    )
    by_status = dict.fromkeys(LIVE_STATUSES, 0)
    # `live` is a Result, not a mapping: .all() gives the (status, count) rows,
    # which update() takes directly as key/value pairs.
    by_status.update(live.all())

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
        "orders_today": int(count or 0),
        "cancelled_today": int(cancelled or 0),
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
    return _ticket(order, datetime.now(UTC), include_events=True)


def _serialise_item(item: MenuItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name,
        "description": item.description,
        "category": item.category,
        "dietary_tags": list(item.dietary_tags),
        "is_available": item.is_available,
        **money.money_fields("price", item.base_price),
    }


async def menu_board(session: AsyncSession, restaurant_id: str) -> list[dict[str, Any]]:
    """Every dish this kitchen owns, including the ones currently 86'd."""
    rows = await session.execute(
        select(MenuItem)
        .options(*_JUST_THE_DISH)
        .where(MenuItem.restaurant_id == restaurant_id, MenuItem.is_active.is_(True))
        .order_by(MenuItem.sort_order, MenuItem.name)
    )
    return [_serialise_item(i) for i in rows.scalars()]


async def add_dish(
    session: AsyncSession,
    restaurant_id: str,
    *,
    name: str,
    category: str,
    price_minor: int,
    description: str = "",
    dietary_tags: list[str] | None = None,
) -> dict[str, Any]:
    """Put a new dish on this restaurant's menu.

    `restaurant_id` comes from the signed-in staff account, never from the
    request, so a restaurant cannot add a dish to somebody else's menu.

    The price arrives already in minor units - the API layer converts once, at
    the boundary, and nothing downstream ever sees a float (Rule $1).
    """
    name = " ".join(name.split())[:120]
    if not name:
        raise ValidationError("A dish needs a name.")

    category = category.strip()
    if category not in menu_service.CATEGORIES:
        raise ValidationError(
            "Choose one of: " + ", ".join(menu_service.CATEGORIES) + "."
        )

    if price_minor <= 0:
        raise ValidationError("A price has to be more than zero.")

    clash = await session.execute(
        select(MenuItem)
        .options(*_JUST_THE_DISH)
        .where(
            MenuItem.restaurant_id == restaurant_id,
            MenuItem.is_active.is_(True),
            func.lower(MenuItem.name) == name.lower(),
        )
    )
    if clash.scalar_one_or_none() is not None:
        raise Conflict(f"{name} is already on your menu.")

    tags = [t for t in (dietary_tags or []) if t in menu_service.DIETARY_TAGS]

    # Ids elsewhere are seeded as r1-m1; a generated suffix keeps the shape
    # while guaranteeing no collision with a future seed.
    item = MenuItem(
        id=f"{restaurant_id}-{uuid.uuid4().hex[:8]}",
        restaurant_id=restaurant_id,
        name=name,
        description=" ".join(description.split())[:400],
        category=category,
        base_price=price_minor,
        dietary_tags=tags,
        allergens=[],
        # Nobody has checked this dish for allergens yet, and saying otherwise
        # would be a safety claim we cannot support (Rule M3).
        allergens_verified=False,
        is_available=True,
        is_active=True,
        sort_order=await _next_sort_order(session, restaurant_id),
    )
    session.add(item)
    await session.flush()
    menu_service.invalidate_cache()
    return _serialise_item(item)


async def _next_sort_order(session: AsyncSession, restaurant_id: str) -> int:
    row = await session.execute(
        select(func.max(MenuItem.sort_order)).where(MenuItem.restaurant_id == restaurant_id)
    )
    return int(row.scalar() or 0) + 10


async def set_availability(
    session: AsyncSession, restaurant_id: str, *, item_id: str, is_available: bool
) -> dict[str, Any]:
    """86 a dish, or bring it back.

    The cached menu is invalidated immediately: a dish taken off at the pass
    must stop being offered on the next turn, not up to a minute later.
    """
    item = await session.get(MenuItem, item_id.strip(), options=_JUST_THE_DISH)
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
