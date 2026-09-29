"""Public menu routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_read_db
from app.services import menu_service, rating_service

router = APIRouter(prefix="/api", tags=["menu"])


@router.get("/menu")
async def menu(
    response: Response,
    session: AsyncSession = Depends(get_read_db),
    q: str | None = None,
    category: str | None = None,
    restaurant_id: str | None = None,
    dietary_tag: str | None = None,
    exclude_allergens: str | None = Query(default=None),
) -> dict:
    response.headers["Cache-Control"] = "public, max-age=60"
    items = await menu_service.search(
        session,
        query=q,
        category=category,
        restaurant_id=restaurant_id,
        dietary_tags=[dietary_tag] if dietary_tag else None,
        exclude_allergens=exclude_allergens.split(",") if exclude_allergens else None,
        limit=10,
    )
    return {"items": items, "categories": menu_service.CATEGORIES}


@router.get("/menu/full")
async def full_menu(
    response: Response, session: AsyncSession = Depends(get_read_db)
) -> dict:
    """The whole menu board in one request: dishes, courses and kitchens.

    Declared above /menu/{item_id} so "full" is not read as an item id.

    The browse UI used to page this by restaurant, because /menu caps a
    response for the agent's sake - one request per kitchen plus two more for
    the list, all of them serial round trips before a single dish appeared.
    """
    response.headers["Cache-Control"] = "public, max-age=60"
    items = await menu_service.offerable(session)
    kitchens = await menu_service.list_restaurants(session)
    scores = await rating_service.summaries(session)
    for kitchen in kitchens:
        kitchen["rating"] = scores.get(kitchen["id"], {"average": None, "count": 0})
    return {
        "items": items,
        "categories": menu_service.CATEGORIES,
        "restaurants": kitchens,
    }


@router.get("/restaurants")
async def restaurants(session: AsyncSession = Depends(get_read_db)) -> dict:
    """The kitchens, each with what its customers scored it.

    Every score is attached in one grouped query rather than per restaurant, so
    adding ratings here costs one extra round trip in total, not one per row.
    """
    items = await menu_service.list_restaurants(session)
    scores = await rating_service.summaries(session)
    for item in items:
        # A restaurant nobody has rated yet carries no score at all, rather than
        # a zero: an unrated kitchen is unknown, not bad.
        item["rating"] = scores.get(item["id"], {"average": None, "count": 0})
    return {"items": items}


@router.get("/menu/{item_id}")
async def menu_item(item_id: str, session: AsyncSession = Depends(get_read_db)) -> dict:
    return await menu_service.get_item(session, item_id)
