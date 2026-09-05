from fastapi import APIRouter

from app.agent.menu import MENU

router = APIRouter(prefix="/api", tags=["menu"])


@router.get("/menu")
async def menu() -> list[dict]:
    return MENU
