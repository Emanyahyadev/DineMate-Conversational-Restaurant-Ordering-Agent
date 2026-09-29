"""Cart rules and the confirmation protocol.

Implements Rules C1-C4 and DOMAIN_MODEL.md section 3. Every method takes
``user_id`` first - there is no way to call one without an owner
(AUTH_SPEC.md section 5).
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload, selectinload

from app.config import settings
from app.db.models import (
    Cart,
    CartLine,
    CartLineOption,
    ConfirmationToken,
    MenuItem,
    MenuOption,
    Restaurant,
)
from app.services import money
from app.services.errors import (
    InvalidOptions,
    ItemNotFound,
    ItemUnavailable,
    LineNotFound,
    QuantityOutOfRange,
)

MAX_QUANTITY = 20


def _options_hash(option_ids: list[str]) -> str:
    """Rule C1: identical item + identical options collapse into one line."""
    if not option_ids:
        return ""
    return hashlib.sha256("|".join(sorted(option_ids)).encode()).hexdigest()[:32]


_LOAD_LINES = (
    # The restaurant name is on every cart line, so it is loaded with the item
    # rather than by MenuItem.restaurant's own selectin - which would also drag
    # that restaurant's whole menu back through Restaurant.items. The option
    # groups are not read here at all; add_line loads the item separately for
    # its Rule O1 check.
    selectinload(Cart.lines)
    .selectinload(CartLine.item)
    .options(
        selectinload(MenuItem.restaurant).noload(Restaurant.items),
        noload(MenuItem.option_groups),
    ),
    selectinload(Cart.lines).selectinload(CartLine.options).selectinload(
        CartLineOption.option
    ),
)


async def get_open_cart(
    session: AsyncSession, user_id: str, *, create: bool = True, lock: bool = False
) -> Cart | None:
    """INV-3: at most one open cart per user.

    Always returns a cart with ``lines`` (and their items and options) eagerly
    loaded - a lazy load in async SQLAlchemy raises MissingGreenlet.

    ``lock`` takes a row lock and is for mutation paths only. Locking on reads
    makes two concurrent GETs of the same cart serialise behind each other,
    which is a hang waiting to happen and buys nothing: a read does not need to
    exclude anyone.
    """
    stmt = select(Cart.id).where(Cart.user_id == user_id, Cart.status == "open")
    if lock:
        stmt = stmt.with_for_update()
    locked = await session.execute(stmt)
    cart_id = locked.scalar_one_or_none()

    if cart_id is None:
        if not create:
            return None
        cart = Cart(user_id=user_id, status="open", version=0)
        session.add(cart)
        await session.flush()
        cart_id = cart.id

    row = await session.execute(
        select(Cart).where(Cart.id == cart_id).options(*_LOAD_LINES)
    )
    return row.scalar_one()


async def reload(session: AsyncSession, cart: Cart) -> Cart:
    """Re-read a cart with its lines after a mutation.

    ``populate_existing`` is required: without it SQLAlchemy hands back the
    identity-mapped object and keeps the collection it loaded earlier, so a
    just-added line would be invisible.
    """
    row = await session.execute(
        select(Cart)
        .where(Cart.id == cart.id)
        .options(*_LOAD_LINES)
        .execution_options(populate_existing=True)
    )
    return row.scalar_one()


async def _bump_version(session: AsyncSession, cart: Cart) -> None:
    """Any mutation invalidates outstanding confirmation tokens (US-15)."""
    cart.version += 1
    await session.flush()


async def serialise(session: AsyncSession, cart: Cart | None) -> dict[str, Any]:
    if cart is None:
        zero = {
            "id": None,
            "version": 0,
            "restaurants": [],
            "restaurant_count": 0,
            "lines": [],
            **money.money_fields("subtotal", 0),
            **money.money_fields("tax", 0),
            **money.money_fields("total", 0),
        }
        return zero

    lines: list[dict[str, Any]] = []
    for line in sorted(cart.lines, key=lambda ln: ln.created_at or datetime.now(UTC)):
        item = line.item
        opts = [
            {"id": o.option.id, "name": o.option.name, "price_delta_cents": o.option.price_delta}
            for o in line.options
        ]
        unit = item.base_price + sum(o["price_delta_cents"] for o in opts)  # Rule O2
        total = money.line_total(unit, line.quantity)
        lines.append(
            {
                "line_id": line.id,
                "item_id": item.id,
                "name": item.name,
                "restaurant_id": item.restaurant_id,
                "restaurant_name": item.restaurant.name if item.restaurant else "",
                "quantity": line.quantity,
                "note": line.note,
                "options": opts,
                **money.money_fields("unit_price", unit),
                **money.money_fields("line_total", total),
            }
        )

    sub = money.subtotal([line["line_total_cents"] for line in lines])
    tax = money.tax_for(sub)

    # Grouped for display, and so the customer can see what each kitchen costs
    # before they commit to a basket that becomes several orders.
    groups: dict[str, dict[str, Any]] = {}
    for line in lines:
        g = groups.setdefault(
            line["restaurant_id"],
            {
                "restaurant_id": line["restaurant_id"],
                "restaurant_name": line["restaurant_name"],
                "lines": [],
                "subtotal_cents": 0,
            },
        )
        g["lines"].append(line)
        g["subtotal_cents"] += line["line_total_cents"]
    for g in groups.values():
        g.update(money.money_fields("subtotal", g["subtotal_cents"]))

    return {
        "id": cart.id,
        "version": cart.version,
        "restaurants": list(groups.values()),
        "restaurant_count": len(groups),
        "lines": lines,
        **money.money_fields("subtotal", sub),
        **money.money_fields("tax", tax),
        **money.money_fields("total", money.order_total(sub, tax)),
        "updated_at": (cart.updated_at or datetime.now(UTC)).isoformat(),
    }


async def view(session: AsyncSession, user_id: str) -> dict[str, Any]:
    cart = await get_open_cart(session, user_id, create=False)
    return await serialise(session, cart)


async def add_line(
    session: AsyncSession,
    user_id: str,
    *,
    item_id: str,
    quantity: int = 1,
    option_ids: list[str] | None = None,
    note: str = "",
) -> dict[str, Any]:
    if not 1 <= quantity <= MAX_QUANTITY:
        raise QuantityOutOfRange(f"Quantity must be between 1 and {MAX_QUANTITY}.")

    # option_groups is genuinely needed below for Rule O1. The restaurant is
    # needed for its name when the cart is serialised - but not its menu, which
    # Restaurant.items would fetch in full behind it.
    item = await session.get(
        MenuItem,
        item_id.strip(),
        options=(selectinload(MenuItem.restaurant).noload(Restaurant.items),),
    )
    if item is None or not item.is_active:
        raise ItemNotFound(f"'{item_id}' is not on the menu.")
    if not item.is_available:  # Rule C3
        raise ItemUnavailable(f"{item.name} is not available today.")

    cart = await get_open_cart(session, user_id, lock=True)
    assert cart is not None

    # A basket may span kitchens. Each one still cooks and dispatches on its own
    # clock, so checkout splits into one order per kitchen (order_service.confirm).
    option_ids = option_ids or []
    options: list[MenuOption] = []
    for oid in option_ids:
        opt = await session.get(MenuOption, oid)
        if opt is None or not opt.is_available:
            raise InvalidOptions(f"Option '{oid}' is not available.")
        if opt.group.menu_item_id != item.id:
            raise InvalidOptions("That choice does not belong to that item.")
        options.append(opt)

    # Rule O1: honour each group's min/max selection
    for group in item.option_groups:
        chosen = [o for o in options if o.option_group_id == group.id]
        if not (group.min_select <= len(chosen) <= group.max_select):
            raise InvalidOptions(
                f"Choose between {group.min_select} and {group.max_select} for {group.name}."
            )

    ohash = _options_hash(option_ids)

    existing = next(
        (ln for ln in cart.lines if ln.menu_item_id == item.id and ln.options_hash == ohash),
        None,
    )
    if existing is not None:  # Rule C1 - merge
        new_qty = existing.quantity + quantity
        if new_qty > MAX_QUANTITY:
            raise QuantityOutOfRange(
                f"That would be {new_qty}; I can add up to {MAX_QUANTITY} of one item."
            )
        existing.quantity = new_qty
    else:
        line = CartLine(
            cart_id=cart.id,
            menu_item_id=item.id,
            quantity=quantity,
            note=note[:200],
            options_hash=ohash,
        )
        session.add(line)
        await session.flush()
        for opt in options:
            session.add(CartLineOption(cart_line_id=line.id, menu_option_id=opt.id))

    await _bump_version(session, cart)
    return await serialise(session, await reload(session, cart))


async def update_line(
    session: AsyncSession, user_id: str, *, line_id: str, quantity: int
) -> dict[str, Any]:
    """SETS the quantity - never increments (US-09). Zero removes (Rule C2)."""
    if not 0 <= quantity <= MAX_QUANTITY:
        raise QuantityOutOfRange(f"Quantity must be between 0 and {MAX_QUANTITY}.")

    cart = await get_open_cart(session, user_id, create=False, lock=True)
    if cart is None:
        raise LineNotFound()
    line = next((ln for ln in cart.lines if ln.id == line_id), None)
    if line is None:
        raise LineNotFound()

    if quantity == 0:
        await session.delete(line)
    else:
        line.quantity = quantity

    await _bump_version(session, cart)
    return await serialise(session, await reload(session, cart))


async def remove_line(session: AsyncSession, user_id: str, *, line_id: str) -> dict[str, Any]:
    return await update_line(session, user_id, line_id=line_id, quantity=0)


async def clear(session: AsyncSession, user_id: str) -> dict[str, Any]:
    cart = await get_open_cart(session, user_id, create=False, lock=True)
    if cart is None:
        return await serialise(session, None)
    for line in list(cart.lines):
        await session.delete(line)
    await _bump_version(session, cart)
    return await serialise(session, await reload(session, cart))


# ------------------------------------------------------- confirmation protocol
async def issue_confirmation_token(
    session: AsyncSession, user_id: str, *, turn_id: str | None = None
) -> str | None:
    """Issued only by a read-back. Returns None for an empty cart.

    The token is the structural guarantee behind KPI A01: the model never sees
    it, so it cannot mint or replay one (ADR-0004).
    """
    cart = await get_open_cart(session, user_id, create=False)
    if cart is None or not cart.lines:
        return None

    token = secrets.token_urlsafe(32)
    session.add(
        ConfirmationToken(
            token=token,
            cart_id=cart.id,
            user_id=user_id,
            cart_version=cart.version,
            issued_turn=turn_id,
            expires_at=datetime.now(UTC)
            + timedelta(seconds=settings.confirmation_token_ttl_seconds),
        )
    )
    await session.flush()
    return token


async def latest_valid_token(
    session: AsyncSession, user_id: str, *, exclude_turn: str | None = None
) -> str | None:
    """The read-back token issued in an EARLIER turn.

    This is what makes consent span two turns: view_cart issues the token in the
    turn that reads the order back, and confirm_order picks it up in the next
    turn, when the customer has actually agreed. Passing ``exclude_turn`` drops
    tokens minted in the current turn, which is the "skipped the read-back" path
    (AGENT_SPEC.md section 4).
    """
    # Only the id and version are needed here: loading the whole cart with its
    # lines costs several extra round trips on every call.
    row = await session.execute(
        select(Cart.id, Cart.version).where(
            Cart.user_id == user_id, Cart.status == "open"
        )
    )
    found = row.first()
    if found is None:
        return None
    cart_id, cart_version = found

    stmt = (
        select(ConfirmationToken)
        .where(
            ConfirmationToken.user_id == user_id,
            ConfirmationToken.cart_id == cart_id,
            ConfirmationToken.cart_version == cart_version,
            ConfirmationToken.consumed_at.is_(None),
            ConfirmationToken.expires_at > datetime.now(UTC),
        )
        .order_by(ConfirmationToken.created_at.desc())
    )
    if exclude_turn:
        stmt = stmt.where(
            (ConfirmationToken.issued_turn.is_(None))
            | (ConfirmationToken.issued_turn != exclude_turn)
        )
    row = await session.execute(stmt.limit(1))
    token = row.scalar_one_or_none()
    return token.token if token else None
