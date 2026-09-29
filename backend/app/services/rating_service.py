"""Ratings: who may leave one, and what they add up to.

A rating belongs to an order, not to a restaurant. That is the whole design:
only a customer whose order actually completed can score it, they can only do it
once, and the restaurant average is therefore made of verified meals rather than
of anyone with an opinion.

All business rules live here. The API layer validates and resolves the session;
it does not decide who may rate.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Order, OrderRating, User
from app.services.errors import Conflict, OrderNotFound, ValidationError

MIN_STARS, MAX_STARS = 1, 5
MAX_COMMENT = 500

#: Only a finished meal can be judged. A cancelled order has nothing to rate.
RATEABLE_STATUSES = {"completed"}


def serialise(rating: OrderRating, *, customer: str | None = None) -> dict[str, Any]:
    return {
        "id": rating.id,
        "order_id": rating.order_id,
        "restaurant_id": rating.restaurant_id,
        "stars": rating.stars,
        "comment": rating.comment,
        "customer": customer,
        "created_at": rating.created_at.isoformat() if rating.created_at else None,
    }


async def rate_order(
    session: AsyncSession,
    user_id: str,
    *,
    order_id: str,
    stars: int,
    comment: str = "",
) -> dict[str, Any]:
    """Record this customer's verdict on their own completed order."""
    if not MIN_STARS <= stars <= MAX_STARS:
        raise ValidationError(f"A rating is between {MIN_STARS} and {MAX_STARS} stars.")

    row = await session.execute(
        select(Order).where(Order.id == order_id.strip().upper(), Order.user_id == user_id)
    )
    order = row.scalar_one_or_none()
    # A foreign order is NOT_FOUND, never FORBIDDEN: a 403 would confirm it exists.
    if order is None:
        raise OrderNotFound()

    if order.status not in RATEABLE_STATUSES:
        raise ValidationError("You can rate an order once it has been completed.")

    existing = await session.execute(
        select(OrderRating).where(OrderRating.order_id == order.id)
    )
    if existing.scalar_one_or_none() is not None:
        raise Conflict("You have already rated that order.")

    rating = OrderRating(
        order_id=order.id,
        user_id=user_id,
        restaurant_id=order.restaurant_id or "",
        stars=stars,
        comment=comment.strip()[:MAX_COMMENT],
    )
    session.add(rating)
    await session.flush()
    return serialise(rating)


async def rating_for_order(
    session: AsyncSession, user_id: str, order_id: str
) -> dict[str, Any] | None:
    row = await session.execute(
        select(OrderRating).where(
            OrderRating.order_id == order_id.strip().upper(),
            OrderRating.user_id == user_id,
        )
    )
    rating = row.scalar_one_or_none()
    return serialise(rating) if rating else None


async def ratings_by_order(session: AsyncSession, user_id: str) -> dict[str, dict[str, Any]]:
    """Every rating this customer has left, keyed by order id."""
    rows = await session.execute(
        select(OrderRating).where(OrderRating.user_id == user_id)
    )
    return {r.order_id: serialise(r) for r in rows.scalars()}


async def scorecard_for(session: AsyncSession, restaurant_id: str) -> dict[str, Any]:
    """Average, count and spread for one restaurant, in a single query.

    The dashboard needs all three together, and the mean is derivable from the
    spread, so asking the database twice for the same rows was a round trip
    spent on arithmetic Python can do for nothing.
    """
    rows = await session.execute(
        select(OrderRating.stars, func.count(OrderRating.id))
        .where(OrderRating.restaurant_id == restaurant_id)
        .group_by(OrderRating.stars)
    )
    counts = dict.fromkeys(range(MIN_STARS, MAX_STARS + 1), 0)
    for star, count in rows:
        counts[int(star)] = int(count)

    total = sum(counts.values())
    stars = sum(star * n for star, n in counts.items())
    return {
        "summary": {
            "average": round(stars / total, 1) if total else None,
            "count": total,
        },
        "distribution": counts,
    }


async def summaries(session: AsyncSession) -> dict[str, dict[str, Any]]:
    """Every restaurant's score in one query, for the customer's restaurant list."""
    rows = await session.execute(
        select(
            OrderRating.restaurant_id,
            func.avg(OrderRating.stars),
            func.count(OrderRating.id),
        ).group_by(OrderRating.restaurant_id)
    )
    return {
        restaurant_id: {"average": round(float(average), 1), "count": int(count)}
        for restaurant_id, average, count in rows
        if restaurant_id
    }


async def recent_for(
    session: AsyncSession, restaurant_id: str, *, limit: int = 8
) -> list[dict[str, Any]]:
    """The latest verdicts, for the restaurant's own dashboard.

    Carries the customer's first name only. The restaurant needs to recognise a
    regular, not to hold a contact record (DATA_MODEL section 6).
    """
    rows = await session.execute(
        select(OrderRating, User.display_name)
        .join(User, User.id == OrderRating.user_id)
        .where(OrderRating.restaurant_id == restaurant_id)
        .order_by(OrderRating.created_at.desc())
        .limit(min(limit, 25))
    )
    out = []
    for rating, display_name in rows:
        first = (display_name or "").strip().split(" ")[0] if display_name else None
        out.append(serialise(rating, customer=first or "A customer"))
    return out
