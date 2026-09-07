"""Public menu routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.services import menu_service

router = APIRouter(prefix="/api", tags=["menu"])


@router.get("/menu")
async def menu(
    response: Response,
    session: AsyncSession = Depends(get_db),
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


@router.get("/restaurants")
async def restaurants(session: AsyncSession = Depends(get_db)) -> dict:
    return {"items": await menu_service.list_restaurants(session)}


@router.get("/menu/{item_id}")
async def menu_item(item_id: str, session: AsyncSession = Depends(get_db)) -> dict:
    return await menu_service.get_item(session, item_id)
