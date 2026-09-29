"""Cart and order routes (API_CONTRACT.md sections 6-7)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user_id, get_db, get_read_db, verify_csrf
from app.config import settings
from app.services import cart_service, money, order_service, rating_service
from app.services.errors import NotFound, Unauthenticated

router = APIRouter(prefix="/api", tags=["orders"])


class AddLineRequest(BaseModel):
    item_id: str
    quantity: int = Field(default=1, ge=1, le=20)
    option_ids: list[str] = Field(default_factory=list)
    note: str = Field(default="", max_length=200)

    model_config = {"extra": "forbid"}


class UpdateLineRequest(BaseModel):
    quantity: int = Field(ge=0, le=20)

    model_config = {"extra": "forbid"}


class ConfirmRequest(BaseModel):
    confirmation_token: str
    fulfilment: str = "pickup"
    contact_phone: str = Field(default="", max_length=32)
    delivery_address: str = Field(default="", max_length=400)
    notes: str = Field(default="", max_length=500)

    model_config = {"extra": "forbid"}


class CancelRequest(BaseModel):
    reason: str = Field(default="", max_length=200)

    model_config = {"extra": "forbid"}


class StatusRequest(BaseModel):
    to_status: str
    actor: str = "staff"
    reason: str = ""

    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------------- cart
@router.get("/cart")
async def get_cart(
    user_id: str = Depends(current_user_id), session: AsyncSession = Depends(get_db)
) -> dict:
    cart = await cart_service.view(session, user_id)
    # Reuse a still-valid token rather than minting one per poll: the UI calls
    # this on every mount and after every turn.
    token = await cart_service.latest_valid_token(session, user_id)
    if token is None:
        token = await cart_service.issue_confirmation_token(session, user_id)

    # Saved details, so a returning customer is not asked for them again.
    from app.db.models import User

    customer = await session.get(User, user_id)
    return {
        "cart": cart,
        "confirmation_token": token,
        "contact": {
            "phone": (customer.phone if customer else None) or "",
            "address": (customer.default_address if customer else None) or "",
        },
        "delivery_fee_display": money.display(settings.delivery_fee),
    }


@router.post("/cart/lines", dependencies=[Depends(verify_csrf)])
async def add_line(
    payload: AddLineRequest,
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_db),
) -> dict:
    cart = await cart_service.add_line(
        session,
        user_id,
        item_id=payload.item_id,
        quantity=payload.quantity,
        option_ids=payload.option_ids,
        note=payload.note,
    )
    return {"cart": cart}


@router.patch("/cart/lines/{line_id}", dependencies=[Depends(verify_csrf)])
async def update_line(
    line_id: str,
    payload: UpdateLineRequest,
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_db),
) -> dict:
    cart = await cart_service.update_line(
        session, user_id, line_id=line_id, quantity=payload.quantity
    )
    return {"cart": cart}


@router.delete("/cart/lines/{line_id}", dependencies=[Depends(verify_csrf)])
async def remove_line(
    line_id: str,
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_db),
) -> dict:
    cart = await cart_service.remove_line(session, user_id, line_id=line_id)
    return {"cart": cart}


@router.delete("/cart", dependencies=[Depends(verify_csrf)])
async def clear_cart(
    user_id: str = Depends(current_user_id), session: AsyncSession = Depends(get_db)
) -> dict:
    return {"cart": await cart_service.clear(session, user_id)}


# -------------------------------------------------------------------- orders
@router.post("/orders", status_code=201, dependencies=[Depends(verify_csrf)])
async def create_order(
    payload: ConfirmRequest,
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    orders = await order_service.confirm(
        session,
        user_id,
        confirmation_token=payload.confirmation_token,
        fulfilment=payload.fulfilment,
        notes=payload.notes,
        contact_phone=payload.contact_phone,
        delivery_address=payload.delivery_address,
        idempotency_key=idempotency_key,
    )
    # A basket spanning kitchens becomes several orders. `order` stays for the
    # single-kitchen case so existing clients keep working.
    return {"orders": orders, "order": orders[0]}


@router.get("/orders")
async def list_orders(
    user_id: str = Depends(current_user_id), session: AsyncSession = Depends(get_read_db)
) -> dict:
    """This customer's orders, each carrying its own rating if they left one.

    Fetched as one keyed lookup rather than a query per order, so the page cost
    does not grow with order history.
    """
    orders = await order_service.list_orders(session, user_id)
    mine = await rating_service.ratings_by_order(session, user_id)
    items = []
    for order in orders:
        data = order_service.serialise(order)
        data["rating"] = mine.get(order.id)
        data["can_rate"] = order.status in rating_service.RATEABLE_STATUSES and (
            order.id not in mine
        )
        items.append(data)
    return {"items": items}


@router.get("/orders/{order_id}")
async def get_order(
    order_id: str,
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_read_db),
) -> dict:
    order = await order_service.get_order(session, user_id, order_id)
    return {"order": order_service.serialise(order, include_events=True)}


@router.post("/orders/{order_id}/cancel", dependencies=[Depends(verify_csrf)])
async def cancel_order(
    order_id: str,
    payload: CancelRequest,
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_db),
) -> dict:
    order = await order_service.cancel(
        session, user_id, order_id=order_id, reason=payload.reason
    )
    return {"order": order}


class RatingRequest(BaseModel):
    stars: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=500)

    model_config = {"extra": "forbid"}


@router.post("/orders/{order_id}/rating", status_code=201, dependencies=[Depends(verify_csrf)])
async def rate_order(
    order_id: str,
    payload: RatingRequest,
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Rate your own completed order. One verdict per order."""
    rating = await rating_service.rate_order(
        session, user_id, order_id=order_id, stars=payload.stars, comment=payload.comment
    )
    return {"rating": rating}


# ------------------------------------------------------------------ internal
internal_router = APIRouter(prefix="/internal", include_in_schema=False)


@internal_router.post("/orders/{order_id}/status")
async def advance_status(
    order_id: str,
    payload: StatusRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """v1 stand-in for a kitchen display system (PRD section 3)."""
    if request.headers.get("X-Internal-Secret") != settings.internal_secret:
        raise Unauthenticated("Invalid internal secret.")

    from sqlalchemy import select

    from app.db.models import Order

    row = await session.execute(select(Order).where(Order.id == order_id.upper()))
    order = row.scalar_one_or_none()
    if order is None:
        raise NotFound()
    order = await order_service.transition(
        session, order, to_status=payload.to_status, actor=payload.actor, reason=payload.reason
    )
    return {"order": order_service.serialise(order, include_events=True)}
