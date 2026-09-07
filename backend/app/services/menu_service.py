"""Menu reads. Implements Rules M1-M3 (DOMAIN_MODEL.md section 1)."""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MenuItem, Restaurant
from app.services.errors import ItemNotFound
from app.services.money import money_fields

CATEGORIES = ["Starters", "Pizza", "Pasta", "Salad", "Sides", "Dessert", "Drinks"]
DIETARY_TAGS = ["vegetarian", "vegan", "gluten_free", "halal", "spicy"]
ALLERGENS = [
    "peanut",
    "tree_nut",
    "dairy",
    "egg",
    "gluten",
    "soy",
    "shellfish",
    "fish",
    "sesame",
]

# In-process TTL cache: the menu is read on nearly every turn and changes rarely
# (ARCHITECTURE.md section 10).
_CACHE: dict[str, Any] = {"at": 0.0, "items": None}
_CACHE_TTL_SECONDS = 60


def _serialise(item: MenuItem) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": item.id,
        "restaurant_id": item.restaurant_id,
        "restaurant_name": item.restaurant.name if item.restaurant else "",
        "name": item.name,
        "description": item.description,
        "category": item.category,
        "dietary_tags": list(item.dietary_tags),
        "allergens": list(item.allergens),
        "allergens_verified": item.allergens_verified,
        "is_available": item.is_available,
    }
    out.update(money_fields("price", item.base_price))
    return out


async def _all_offerable(session: AsyncSession) -> list[dict[str, Any]]:
    now = time.monotonic()
    if _CACHE["items"] is not None and now - _CACHE["at"] < _CACHE_TTL_SECONDS:
        return _CACHE["items"]  # type: ignore[return-value]

    rows = await session.execute(
        select(MenuItem)
        .join(Restaurant)
        .where(
            MenuItem.is_active.is_(True),
            MenuItem.is_available.is_(True),  # Rule M1
            Restaurant.is_active.is_(True),
        )
        .order_by(Restaurant.sort_order, MenuItem.sort_order, MenuItem.name)
    )
    items = [_serialise(i) for i in rows.scalars()]
    _CACHE["items"], _CACHE["at"] = items, now
    return items


def invalidate_cache() -> None:
    _CACHE["items"] = None


async def search(
    session: AsyncSession,
    *,
    query: str | None = None,
    category: str | None = None,
    restaurant_id: str | None = None,
    dietary_tags: list[str] | None = None,
    exclude_allergens: list[str] | None = None,
    limit: int = 6,
) -> list[dict[str, Any]]:
    items = await _all_offerable(session)

    if restaurant_id:
        items = [i for i in items if i["restaurant_id"] == restaurant_id.strip()]
    if category:
        items = [i for i in items if i["category"].lower() == category.strip().lower()]
    if dietary_tags:
        wanted = {t.strip().lower() for t in dietary_tags}
        items = [i for i in items if wanted.issubset(set(i["dietary_tags"]))]
    if exclude_allergens:
        banned = {a.strip().lower() for a in exclude_allergens}
        # Rule M3: unverified allergen data is not a safety guarantee, so an
        # unverified item is excluded whenever an allergen filter is in play.
        items = [
            i
            for i in items
            if i["allergens_verified"] and not banned.intersection(set(i["allergens"]))
        ]
    if query:
        q = query.strip().lower()
        terms = [t for t in q.split() if len(t) > 2]

        def score(i: dict[str, Any]) -> int:
            hay = f"{i['name']} {i['description']} {' '.join(i['dietary_tags'])}".lower()
            if q in hay:
                return 100
            return sum(1 for t in terms if t in hay)

        scored = [(score(i), i) for i in items]
        matched = [i for s, i in scored if s > 0]
        items = matched if matched else items

    return items[: max(1, min(limit, 10))]


async def get_item(session: AsyncSession, item_id: str) -> dict[str, Any]:
    item = await session.get(MenuItem, item_id.strip())
    if item is None or not item.is_active:
        raise ItemNotFound(f"'{item_id}' is not on the menu.")

    data = _serialise(item)
    data["option_groups"] = [
        {
            "id": g.id,
            "name": g.name,
            "min_select": g.min_select,
            "max_select": g.max_select,
            "options": [
                {
                    "id": o.id,
                    "name": o.name,
                    **money_fields("price_delta", o.price_delta),
                }
                for o in sorted(g.options, key=lambda o: o.sort_order)
                if o.is_available
            ],
        }
        for g in sorted(item.option_groups, key=lambda g: g.sort_order)
    ]
    return data


async def resolve_by_name(session: AsyncSession, name: str) -> list[dict[str, Any]]:
    """Name to candidate items. More than one result means ambiguity (US-11)."""
    items = await _all_offerable(session)
    needle = name.strip().lower()
    exact = [i for i in items if i["name"].lower() == needle]
    if exact:
        return exact
    return [i for i in items if needle in i["name"].lower()]


async def list_restaurants(session: AsyncSession) -> list[dict[str, Any]]:
    rows = await session.execute(
        select(Restaurant)
        .where(Restaurant.is_active.is_(True))
        .order_by(Restaurant.sort_order, Restaurant.name)
    )
    restaurants = list(rows.scalars())
    items = await _all_offerable(session)

    out = []
    for r in restaurants:
        mine = [i for i in items if i["restaurant_id"] == r.id]
        out.append(
            {
                "id": r.id,
                "name": r.name,
                "cuisine": r.cuisine,
                "description": r.description,
                "item_count": len(mine),
                "categories": sorted({i["category"] for i in mine}),
                "dietary_tags": sorted({t for i in mine for t in i["dietary_tags"]}),
            }
        )
    return out
