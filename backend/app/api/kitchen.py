"""Staff-facing routes: the kitchen dashboard.

Every route resolves the caller's own restaurant from their account. There is
no restaurant_id parameter anywhere here, for the same reason no customer tool
takes a user_id: if it cannot be named, it cannot be forged.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user_id, get_db, get_read_db, verify_csrf
from app.services import kitchen_service, menu_service, money, rating_service
from app.services.errors import ValidationError

router = APIRouter(prefix="/api/kitchen", tags=["kitchen"])


class AdvanceRequest(BaseModel):
    to_status: str
    reason: str = Field(default="", max_length=200)

    model_config = {"extra": "forbid"}


class AvailabilityRequest(BaseModel):
    is_available: bool

    model_config = {"extra": "forbid"}


class NewDishRequest(BaseModel):
    """Note there is no restaurant_id: it comes from the signed-in account."""

    name: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=32)
    # A string, so "1,650" and "Rs 1650" both work and no float is ever parsed.
    price: str = Field(min_length=1, max_length=24)
    description: str = Field(default="", max_length=400)
    dietary_tags: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


@router.get("/me")
async def whoami(
    user_id: str = Depends(current_user_id), session: AsyncSession = Depends(get_read_db)
) -> dict:
    """Who this staff member is, and which kitchen they belong to."""
    staff = await kitchen_service.require_staff(session, user_id)
    restaurant = await kitchen_service.restaurant_for(session, staff)
    return {
        "staff": {"id": staff.id, "email": staff.email, "name": staff.display_name},
        "restaurant": {
            "id": restaurant.id,
            "name": restaurant.name,
            "cuisine": restaurant.cuisine,
        },
    }


@router.get("/orders")
async def live_orders(
    user_id: str = Depends(current_user_id), session: AsyncSession = Depends(get_read_db)
) -> dict:
    staff = await kitchen_service.require_staff(session, user_id)
    return {
        "items": await kitchen_service.queue(session, staff.staff_restaurant_id),
        "stats": await kitchen_service.stats(session, staff.staff_restaurant_id),
    }


@router.get("/orders/history")
async def order_history(
    user_id: str = Depends(current_user_id), session: AsyncSession = Depends(get_read_db)
) -> dict:
    staff = await kitchen_service.require_staff(session, user_id)
    return {"items": await kitchen_service.history(session, staff.staff_restaurant_id)}


@router.post("/orders/{order_id}/advance", dependencies=[Depends(verify_csrf)])
async def advance_order(
    order_id: str,
    payload: AdvanceRequest,
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_db),
) -> dict:
    staff = await kitchen_service.require_staff(session, user_id)
    order = await kitchen_service.advance(
        session,
        staff.staff_restaurant_id,
        order_id=order_id,
        to_status=payload.to_status,
        reason=payload.reason,
    )
    return {"order": order}


@router.get("/menu")
async def menu_board(
    user_id: str = Depends(current_user_id), session: AsyncSession = Depends(get_read_db)
) -> dict:
    staff = await kitchen_service.require_staff(session, user_id)
    return {"items": await kitchen_service.menu_board(session, staff.staff_restaurant_id)}


@router.post("/menu", status_code=201, dependencies=[Depends(verify_csrf)])
async def add_dish(
    payload: NewDishRequest,
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Add a dish to the signed-in restaurant's own menu."""
    staff = await kitchen_service.require_staff(session, user_id)
    try:
        price_minor = money.to_minor(payload.price)
    except ValueError:
        raise ValidationError("That price is not a number we recognise.") from None

    item = await kitchen_service.add_dish(
        session,
        staff.staff_restaurant_id,
        name=payload.name,
        category=payload.category,
        price_minor=price_minor,
        description=payload.description,
        dietary_tags=payload.dietary_tags,
    )
    return {"item": item}


@router.get("/ratings")
async def ratings(
    user_id: str = Depends(current_user_id), session: AsyncSession = Depends(get_read_db)
) -> dict:
    """What this restaurant's own customers thought."""
    staff = await kitchen_service.require_staff(session, user_id)
    restaurant_id = staff.staff_restaurant_id
    scorecard = await rating_service.scorecard_for(session, restaurant_id)
    return {**scorecard, "recent": await rating_service.recent_for(session, restaurant_id)}


@router.get("/menu/categories")
async def menu_categories() -> dict:
    """The categories a dish may belong to, so the form cannot offer a bad one."""
    return {"items": menu_service.CATEGORIES, "dietary_tags": menu_service.DIETARY_TAGS}


@router.patch("/menu/{item_id}", dependencies=[Depends(verify_csrf)])
async def set_availability(
    item_id: str,
    payload: AvailabilityRequest,
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_db),
) -> dict:
    staff = await kitchen_service.require_staff(session, user_id)
    item = await kitchen_service.set_availability(
        session,
        staff.staff_restaurant_id,
        item_id=item_id,
        is_available=payload.is_available,
    )
    return {"item": item}
