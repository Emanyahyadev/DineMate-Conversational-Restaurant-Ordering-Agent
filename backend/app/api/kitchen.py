"""Staff-facing routes: the kitchen dashboard.

Every route resolves the caller's own restaurant from their account. There is
no restaurant_id parameter anywhere here, for the same reason no customer tool
takes a user_id: if it cannot be named, it cannot be forged.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user_id, get_db, verify_csrf
from app.services import kitchen_service

router = APIRouter(prefix="/api/kitchen", tags=["kitchen"])


class AdvanceRequest(BaseModel):
    to_status: str
    reason: str = Field(default="", max_length=200)

    model_config = {"extra": "forbid"}


class AvailabilityRequest(BaseModel):
    is_available: bool

    model_config = {"extra": "forbid"}


@router.get("/me")
async def whoami(
    user_id: str = Depends(current_user_id), session: AsyncSession = Depends(get_db)
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
    user_id: str = Depends(current_user_id), session: AsyncSession = Depends(get_db)
) -> dict:
    staff = await kitchen_service.require_staff(session, user_id)
    return {
        "items": await kitchen_service.queue(session, staff.staff_restaurant_id),
        "stats": await kitchen_service.stats(session, staff.staff_restaurant_id),
    }


@router.get("/orders/history")
async def order_history(
    user_id: str = Depends(current_user_id), session: AsyncSession = Depends(get_db)
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
    user_id: str = Depends(current_user_id), session: AsyncSession = Depends(get_db)
) -> dict:
    staff = await kitchen_service.require_staff(session, user_id)
    return {"items": await kitchen_service.menu_board(session, staff.staff_restaurant_id)}


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
