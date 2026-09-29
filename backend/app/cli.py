"""Operational commands: python -m app.cli <command>"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import yaml
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import (
    Cart,
    ConfirmationToken,
    MenuItem,
    MenuOption,
    MenuOptionGroup,
    Order,
    OrderEvent,
    OrderLine,
    Restaurant,
    User,
)
from app.db.postgres import SessionLocal
from app.services import memory_service, menu_service

SEED_PATH = Path(__file__).parent.parent / "seeds" / "restaurants.yaml"


async def seed_menu() -> None:
    """Idempotent: re-running updates in place rather than duplicating."""
    data = yaml.safe_load(SEED_PATH.read_text(encoding="utf-8"))
    item_count = 0

    async with SessionLocal() as session:
        for spec in data:
            restaurant = await session.get(Restaurant, spec["id"])
            if restaurant is None:
                restaurant = Restaurant(id=spec["id"])
                session.add(restaurant)
            restaurant.name = spec["name"]
            restaurant.cuisine = spec.get("cuisine", "")
            restaurant.description = spec.get("description", "")
            restaurant.is_active = spec.get("is_active", True)
            restaurant.sort_order = spec.get("sort_order", 0)
            await session.flush()

            for i, entry in enumerate(spec.get("items", [])):
                entry.setdefault("sort_order", (i + 1) * 10)
                entry["restaurant_id"] = restaurant.id
                item_count += 1
                await _upsert_item(session, entry)
        await session.commit()

    menu_service.invalidate_cache()
    print(f"seeded {len(data)} restaurants, {item_count} menu items")


async def _upsert_item(session: AsyncSession, entry: dict) -> None:
    item = await session.get(MenuItem, entry["id"])
    if item is None:
        item = MenuItem(id=entry["id"])
        session.add(item)

    item.restaurant_id = entry["restaurant_id"]
    item.name = entry["name"]
    item.description = entry.get("description", "")
    item.category = entry["category"]
    item.base_price = entry["base_price"]
    item.dietary_tags = entry.get("dietary_tags", [])
    item.allergens = entry.get("allergens", [])
    item.allergens_verified = entry.get("allergens_verified", False)
    item.is_available = entry.get("is_available", True)
    item.is_active = True
    item.sort_order = entry.get("sort_order", 0)
    await session.flush()

    for group in entry.get("option_groups", []):
        existing = await session.execute(
            select(MenuOptionGroup).where(
                MenuOptionGroup.menu_item_id == item.id,
                MenuOptionGroup.name == group["name"],
            )
        )
        if existing.scalar_one_or_none() is not None:
            continue
        g = MenuOptionGroup(
            menu_item_id=item.id,
            name=group["name"],
            min_select=group.get("min_select", 0),
            max_select=group.get("max_select", 1),
        )
        session.add(g)
        await session.flush()
        for i, opt in enumerate(group.get("options", [])):
            session.add(
                MenuOption(
                    option_group_id=g.id,
                    name=opt["name"],
                    price_delta=opt.get("price_delta", 0),
                    sort_order=i,
                )
            )


async def check_invariants() -> int:
    """Nightly sweep behind KPI R08. Exit code is the violation count."""
    violations: list[str] = []
    async with SessionLocal() as session:
        # INV-5: every order has at least one line
        rows = await session.execute(
            select(Order.id).outerjoin(OrderLine).group_by(Order.id).having(
                func.count(OrderLine.id) == 0
            )
        )
        for (oid,) in rows:
            violations.append(f"INV-5 order {oid} has no lines")

        # INV-4: total consistency, recomputed from stored snapshots
        orders = await session.execute(select(Order))
        for order in orders.scalars():
            if order.total != order.subtotal + order.tax + order.delivery_fee:
                violations.append(f"INV-4 order {order.id} total mismatch")
            line_sum = sum(ln.line_total for ln in order.lines)
            if order.subtotal != line_sum:
                violations.append(f"INV-4 order {order.id} subtotal != sum(lines)")

        # INV-6: every order has at least one event
        rows = await session.execute(
            select(Order.id).outerjoin(OrderEvent).group_by(Order.id).having(
                func.count(OrderEvent.id) == 0
            )
        )
        for (oid,) in rows:
            violations.append(f"INV-6 order {oid} has no events")

        # INV-8: no order without a consumed token.
        #
        # Checked per CHECKOUT, not per order. A basket spanning kitchens
        # consumes one token and creates one order per kitchen, so counting
        # orders against tokens was only ever right when the two were 1:1.
        consumed = await session.execute(
            select(func.count()).select_from(ConfirmationToken).where(
                ConfirmationToken.consumed_at.isnot(None)
            )
        )
        checkouts = await session.execute(
            select(func.count(func.distinct(Order.order_group_id)))
        )
        if (checkouts.scalar() or 0) > (consumed.scalar() or 0):
            violations.append("INV-8 more checkouts than consumed confirmation tokens")

        # Every order belongs to a checkout, so the check above cannot be
        # sidestepped by writing an order with no group.
        row = await session.execute(
            select(func.count()).select_from(Order).where(Order.order_group_id.is_(None))
        )
        orphans = row.scalar() or 0
        if orphans:
            violations.append(f"INV-8 {orphans} order(s) with no checkout group")

        # INV-3: at most one open cart per user
        rows = await session.execute(
            select(Cart.user_id).where(Cart.status == "open").group_by(Cart.user_id).having(
                func.count(Cart.id) > 1
            )
        )
        for (uid,) in rows:
            violations.append(f"INV-3 user {uid} has multiple open carts")

    for v in violations:
        print("VIOLATION:", v)
    print(f"invariant sweep: {len(violations)} violation(s)")
    return len(violations)


async def delete_user(user_id: str) -> None:
    """Cross-store deletion (DATA_MODEL.md section 6)."""
    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        if user is None:
            print("no such user")
            return
        # Orders are retained for tax but anonymised.
        orders = await session.execute(select(Order).where(Order.user_id == user_id))
        for order in orders.scalars():
            order.notes = ""
        user.email = f"deleted-{user_id[:8]}@invalid"
        user.display_name = None
        user.password_hash = None
        user.status = "deleted"
        await session.execute(delete(Cart).where(Cart.user_id == user_id))
        await session.commit()
    await memory_service.forget_all(user_id)
    print(f"deleted user {user_id} across both stores")


async def make_staff(email: str, restaurant_id: str, password: str) -> None:
    """Create or promote a kitchen account: python -m app.cli staff <email> <r-id> <pw>"""
    from app.services import auth_service

    async with SessionLocal() as session:
        restaurant = await session.get(Restaurant, restaurant_id)
        if restaurant is None:
            print(f"no such restaurant: {restaurant_id}")
            return

        row = await session.execute(select(User).where(User.email == email.lower()))
        user = row.scalar_one_or_none()
        if user is None:
            user = await auth_service.register(
                session, email=email, password=password, display_name=f"{restaurant.name} kitchen"
            )
        user.role = "staff"
        user.staff_restaurant_id = restaurant.id
        await session.commit()
    print(f"{email} is now staff at {restaurant.name} ({restaurant_id})")


DEMO_PASSWORD = "DineMate2026!Demo"

# One diner and one chef per kitchen, so both sides of the app can be opened
# with a login you can actually type. Re-running resets the password, which is
# the point: these are demonstration accounts, not real ones.
DEMO_CUSTOMERS = [
    ("ayesha.khan@dinemate.app", "Ayesha Khan"),
    ("bilal.ahmed@dinemate.app", "Bilal Ahmed"),
]
DEMO_CHEFS = [
    ("imran.lahori@dinemate.app", "Imran Malik", "r1"),
    ("sana.karachi@dinemate.app", "Sana Qureshi", "r2"),
    ("adnan.sindhi@dinemate.app", "Adnan Shah", "r3"),
    ("gulzar.peshawari@dinemate.app", "Gulzar Khan", "r4"),
    ("nadia.chaikhana@dinemate.app", "Nadia Iqbal", "r5"),
]


async def seed_demo() -> None:
    """Create (or reset) the demo logins: python -m app.cli seed-demo"""
    from app.services import auth_service

    async with SessionLocal() as session:

        async def upsert(email: str, name: str, restaurant_id: str | None) -> None:
            row = await session.execute(select(User).where(User.email == email.lower()))
            user = row.scalar_one_or_none()
            if user is None:
                user = await auth_service.register(
                    session, email=email, password=DEMO_PASSWORD, display_name=name
                )
            else:
                # Reset, so the documented password is always the real one.
                user.password_hash = auth_service.hash_password(DEMO_PASSWORD)
                user.display_name = name
            user.status = "active"
            user.role = "staff" if restaurant_id else "customer"
            user.staff_restaurant_id = restaurant_id
            where = "customer"
            if restaurant_id:
                restaurant = await session.get(Restaurant, restaurant_id)
                where = restaurant.name if restaurant else restaurant_id
            print(f"  {email:32} {name:14} {where}")

        print("Customers:")
        for email, name in DEMO_CUSTOMERS:
            await upsert(email, name, None)
        print("Kitchen staff:")
        for email, name, restaurant_id in DEMO_CHEFS:
            await upsert(email, name, restaurant_id)

        await session.commit()

    print(f"\nPassword for every account above: {DEMO_PASSWORD}")


async def clear_orders() -> None:
    """Delete every order, cart and rating: python -m app.cli clear-orders

    For clearing demonstration data out of a development database so the
    kitchen board shows only orders you placed yourself. Refuses to run against
    a production environment, because this is not recoverable.
    """
    if settings.is_production:
        print("refusing to clear orders in production")
        raise SystemExit(1)

    from app.db.models import CartLine, CartLineOption, OrderRating

    async with SessionLocal() as session:
        # Children first: every one of these references the row below it.
        for model in (
            OrderRating,
            OrderEvent,
            OrderLine,
            Order,
            ConfirmationToken,
            CartLineOption,
            CartLine,
            Cart,
        ):
            result = await session.execute(delete(model))
            print(f"  cleared {model.__tablename__:24} {result.rowcount} rows")
        await session.commit()
    print("\nEvery order is gone. The kitchen board is empty until someone orders.")


def main() -> None:
    if len(sys.argv) < 2:
        print(
            "usage: python -m app.cli "
            "[seed-menu|seed-demo|clear-orders|check-invariants|delete-user <id>"
            "|staff <email> <restaurant> <password>]"
        )
        raise SystemExit(2)

    command = sys.argv[1]
    if command == "seed-menu":
        asyncio.run(seed_menu())
    elif command == "seed-demo":
        asyncio.run(seed_demo())
    elif command == "clear-orders":
        asyncio.run(clear_orders())
    elif command == "check-invariants":
        raise SystemExit(1 if asyncio.run(check_invariants()) else 0)
    elif command == "delete-user":
        asyncio.run(delete_user(sys.argv[2]))
    elif command == "staff":
        asyncio.run(make_staff(sys.argv[2], sys.argv[3], sys.argv[4]))
    else:
        print(f"unknown command: {command}")
        raise SystemExit(2)


if __name__ == "__main__":
    main()
