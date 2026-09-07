"""The nine agent tools (AGENT_SPEC.md section 5).

Universal contract:
  * ``user_id`` is never a parameter - it comes from RunContextWrapper[ChatContext].
  * Every tool returns a success object or {"error": {"code", "message"}}.
  * Money crosses as *_cents plus a preformatted *_display the model echoes verbatim.
"""

from __future__ import annotations

from typing import Any

from agents import RunContextWrapper, function_tool

from app.agent.context import ChatContext
from app.services import cart_service, memory_service, menu_service, order_service
from app.services.errors import DomainError, NoConfirmation, OrderNotFound


def _as_list(value: Any) -> list[str] | None:
    """Coerce a model-supplied list argument.

    Models routinely send a bare string where the schema asks for an array
    ("dietary_tags": "vegetarian"). Strict validation turns that into a failed
    tool call, and the agent then retries until it exhausts its turns - the
    customer sees nothing at all. Accepting both shapes costs nothing and keeps
    a formatting slip from becoming a dead conversation.
    """
    if value is None:
        return None
    if isinstance(value, str):
        parts = [p.strip() for p in value.replace("|", ",").split(",")]
        return [p for p in parts if p] or None
    if isinstance(value, (list, tuple, set)):
        out = [str(v).strip() for v in value if str(v).strip()]
        return out or None
    return None


def _as_text(value: Any) -> str | None:
    """Empty strings mean "not specified", not "match the empty string"."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _err(exc: DomainError) -> dict[str, Any]:
    return {"error": {"code": exc.code, "message": exc.message, **exc.details}}


def _tool(name: str):
    """Wrap a tool body: record the call, convert domain errors into results."""

    def decorate(fn):
        async def wrapper(ctx: RunContextWrapper[ChatContext], **kwargs: Any) -> Any:
            c = ctx.context
            try:
                result = await fn(c, **kwargs)
            except DomainError as exc:
                result = _err(exc)
            c.record(name, kwargs, result)
            return result

        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        return wrapper

    return decorate


# --------------------------------------------------------------------- menu
@function_tool
async def search_menu(
    ctx: RunContextWrapper[ChatContext],
    query: str | None = None,
    category: str | None = None,
    restaurant_id: str | None = None,
    dietary_tags: Any = None,
    exclude_allergens: Any = None,
    limit: int = 6,
) -> list[dict[str, Any]] | dict[str, Any]:
    """Find dishes across every restaurant on DineMate. Use this for any question
    about what is available.

    Args:
        query: Free text, e.g. 'something spicy' or 'pizza'.
        category: One of Starters, Pizza, Pasta, Salad, Sides, Dessert, Drinks.
        restaurant_id: Restrict to one restaurant, e.g. 'r2'. Use list_restaurants first.
        dietary_tags: Restrict to vegetarian, vegan, gluten_free, halal or spicy.
        exclude_allergens: Leave out dishes containing these allergens.
        limit: How many dishes to return, 1 to 10.
    """
    c = ctx.context
    dietary_tags = _as_list(dietary_tags)
    exclude_allergens = _as_list(exclude_allergens)
    category = _as_text(category)
    restaurant_id = _as_text(restaurant_id)
    query = _as_text(query)

    # The customer's recorded allergies are enforced server-side, so the model
    # forgetting to pass them cannot produce an unsafe suggestion (Rule N3).
    profile = await memory_service.get_profile(c.user_id)
    known = [
        word
        for f in profile.get("facts", [])
        if f.get("kind") == "allergy"
        for word in menu_service.ALLERGENS
        if word in f.get("text", "").lower()
    ]
    banned = sorted(set((exclude_allergens or []) + known))

    result = await menu_service.search(
        c.session,
        query=query,
        category=category,
        restaurant_id=restaurant_id,
        dietary_tags=dietary_tags,
        exclude_allergens=banned or None,
        limit=limit,
    )
    c.record(
        "search_menu",
        {
            "query": query,
            "category": category,
            "restaurant_id": restaurant_id,
            "dietary_tags": dietary_tags,
            "exclude_allergens": exclude_allergens,
            "limit": limit,
        },
        result,
    )
    return result


@function_tool
async def get_item_details(
    ctx: RunContextWrapper[ChatContext], item_id: str
) -> dict[str, Any]:
    """Get the full description, price, allergens and choices for one dish.

    Args:
        item_id: The dish id from search_menu, e.g. 'm1'.
    """
    c = ctx.context
    try:
        result = await menu_service.get_item(c.session, item_id)
    except DomainError as exc:
        result = _err(exc)
    c.record("get_item_details", {"item_id": item_id}, result)
    return result


@function_tool
async def list_restaurants(ctx: RunContextWrapper[ChatContext]) -> list[dict[str, Any]]:
    """List the restaurants on DineMate with their cuisine and what they offer.
    Use this when the customer asks who is available or wants a particular cuisine."""
    c = ctx.context
    result = await menu_service.list_restaurants(c.session)
    c.record("list_restaurants", {}, result)
    return result


# --------------------------------------------------------------------- cart
@function_tool
async def add_to_cart(
    ctx: RunContextWrapper[ChatContext],
    item_id: str,
    quantity: int = 1,
    option_ids: Any = None,
    note: str = "",
) -> dict[str, Any]:
    """Add a dish to the customer's order. Only call this when they asked for it.

    Args:
        item_id: The dish id, e.g. 'm1'.
        quantity: How many, 1 to 20.
        option_ids: Chosen option ids from get_item_details, if the dish has choices.
        note: Any special instruction for this dish.
    """
    c = ctx.context
    try:
        result = await cart_service.add_line(
            c.session,
            c.user_id,
            item_id=item_id,
            quantity=quantity,
            option_ids=_as_list(option_ids) or [],
            note=note,
        )
        c.cart_snapshot = result
    except DomainError as exc:
        result = _err(exc)
    c.record(
        "add_to_cart",
        {"item_id": item_id, "quantity": quantity, "option_ids": _as_list(option_ids) or [], "note": note},
        result,
    )
    return result


@function_tool
async def update_cart_item(
    ctx: RunContextWrapper[ChatContext], line_id: str, quantity: int
) -> dict[str, Any]:
    """Set the quantity of something already in the order. This SETS the number,
    it does not add to it. Use 0 to take the item out.

    Args:
        line_id: The line_id from the cart, not the dish id.
        quantity: The new total quantity, 0 to 20.
    """
    c = ctx.context
    try:
        result = await cart_service.update_line(
            c.session, c.user_id, line_id=line_id, quantity=quantity
        )
        c.cart_snapshot = result
    except DomainError as exc:
        result = _err(exc)
    c.record("update_cart_item", {"line_id": line_id, "quantity": quantity}, result)
    return result


@function_tool
async def remove_from_cart(ctx: RunContextWrapper[ChatContext], line_id: str) -> dict[str, Any]:
    """Take a dish out of the order entirely.

    Args:
        line_id: The line_id from the cart.
    """
    c = ctx.context
    try:
        result = await cart_service.remove_line(c.session, c.user_id, line_id=line_id)
        c.cart_snapshot = result
    except DomainError as exc:
        result = _err(exc)
    c.record("remove_from_cart", {"line_id": line_id}, result)
    return result


@function_tool
async def view_cart(ctx: RunContextWrapper[ChatContext]) -> dict[str, Any]:
    """Look at the current order with its exact total. Call this before reading the
    order back to the customer, and any time they ask what they have or what it costs."""
    c = ctx.context
    result = await cart_service.view(c.session, c.user_id)
    c.cart_snapshot = result

    # Issuing the confirmation token is the read-back's side effect. The token is
    # kept server-side; the model never sees it (ADR-0004).
    if result["lines"]:
        token = await cart_service.issue_confirmation_token(
            c.session, c.user_id, turn_id=c.turn_id
        )
        if token:
            c.confirmation_token = token
            c.token_issued_this_turn = True

    c.record("view_cart", {}, result)
    return result


# -------------------------------------------------------------------- orders
@function_tool
async def confirm_order(
    ctx: RunContextWrapper[ChatContext], fulfilment: str = "pickup", notes: str = ""
) -> dict[str, Any]:
    """Place the order. Only call this immediately after you read the order back and
    the customer agreed in their last message.

    Args:
        fulfilment: 'pickup' or 'delivery'.
        notes: Any instruction for the whole order.
    """
    c = ctx.context
    try:
        # The token must come from a read-back in an EARLIER turn: consent has to
        # be attributable to a customer message that followed it (ADR-0004).
        token = await cart_service.latest_valid_token(
            c.session, c.user_id, exclude_turn=c.turn_id
        )
        if token is None:
            raise NoConfirmation(
                "Read the order back to the customer and wait for them to agree first."
            )
        result = await order_service.confirm(
            c.session,
            c.user_id,
            confirmation_token=token,
            fulfilment=fulfilment,
            notes=notes,
            idempotency_key=f"turn-{c.turn_id}",
        )
        c.confirmation_token = None
        c.cart_snapshot = await cart_service.view(c.session, c.user_id)
    except DomainError as exc:
        result = _err(exc)
    c.record("confirm_order", {"fulfilment": fulfilment, "notes": notes}, result)
    return result


@function_tool
async def order_status(
    ctx: RunContextWrapper[ChatContext], order_id: str | None = None
) -> dict[str, Any]:
    """Check where one of this customer's orders has got to.

    Args:
        order_id: The order id, e.g. 'ORD-482910'. Leave it out for their latest order.
    """
    c = ctx.context
    try:
        if order_id:
            order = await order_service.get_order(c.session, c.user_id, order_id)
        else:
            order = await order_service.latest_open_order(c.session, c.user_id)
            if order is None:
                result = {"error": {"code": "ORDER_NOT_FOUND", "message": "No open orders."}}
                c.record("order_status", {"order_id": order_id}, result)
                return result
        result = order_service.serialise(order, include_events=True)
    except DomainError as exc:
        result = _err(exc)
    c.record("order_status", {"order_id": order_id}, result)
    return result


@function_tool
async def cancel_order(
    ctx: RunContextWrapper[ChatContext], order_id: str | None = None, reason: str = ""
) -> dict[str, Any]:
    """Cancel an order, if it is still within the cancellation window. Only call this
    when the customer has clearly asked to cancel.

    Args:
        order_id: The order id to cancel. Leave it out for their latest order.
        reason: Why they are cancelling, if they said.
    """
    c = ctx.context
    try:
        target = (order_id or "").strip()
        if not target:
            latest = await order_service.latest_open_order(c.session, c.user_id)
            if latest is None:
                raise OrderNotFound("You do not have an order I can cancel.")
            target = latest.id
        result = await order_service.cancel(c.session, c.user_id, order_id=target, reason=reason)
    except DomainError as exc:
        result = _err(exc)
    c.record("cancel_order", {"order_id": order_id, "reason": reason}, result)
    return result


TOOLS = [
    list_restaurants,
    search_menu,
    get_item_details,
    add_to_cart,
    update_cart_item,
    remove_from_cart,
    view_cart,
    confirm_order,
    order_status,
    cancel_order,
]
