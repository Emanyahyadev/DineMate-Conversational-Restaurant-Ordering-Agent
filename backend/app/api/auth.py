"""Auth routes (API_CONTRACT.md section 3)."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    REFRESH_COOKIE,
    clear_auth_cookies,
    current_user_id,
    get_db,
    get_read_db,
    set_auth_cookies,
)
from app.db.models import User
from app.services import auth_service
from app.services.errors import Unauthenticated

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=200)
    display_name: str | None = Field(default=None, max_length=80)

    model_config = {"extra": "forbid"}


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=200)

    model_config = {"extra": "forbid"}


async def _issue(response: Response, session: AsyncSession, user: User, request: Request) -> dict:
    row, raw_refresh = await auth_service.create_session(
        session,
        user,
        user_agent=request.headers.get("user-agent", ""),
        ip=request.client.host if request.client else "",
    )
    access = auth_service.create_access_token(user.id, row.id)
    set_auth_cookies(
        response, access=access, refresh=raw_refresh, csrf=secrets.token_urlsafe(24)
    )
    return {"user": auth_service.serialise_user(user)}


@router.post("/register", status_code=201)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db),
) -> dict:
    user = await auth_service.register(
        session,
        email=payload.email,
        password=payload.password,
        display_name=payload.display_name,
    )
    return await _issue(response, session, user, request)


@router.post("/login")
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db),
) -> dict:
    user = await auth_service.authenticate(
        session, email=payload.email, password=payload.password
    )
    return await _issue(response, session, user, request)


@router.post("/refresh")
async def refresh(
    request: Request, response: Response, session: AsyncSession = Depends(get_db)
) -> dict:
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise Unauthenticated("Please sign in again.")
    user, row, new_raw = await auth_service.rotate_session(session, raw)
    access = auth_service.create_access_token(user.id, row.id)
    set_auth_cookies(
        response, access=access, refresh=new_raw, csrf=secrets.token_urlsafe(24)
    )
    return {"user": auth_service.serialise_user(user)}


@router.post("/logout", status_code=204)
async def logout(
    request: Request, response: Response, session: AsyncSession = Depends(get_db)
) -> Response:
    token = request.cookies.get("dm_access")
    if token:
        try:
            payload = auth_service.decode_access_token(token)
            if payload.get("sid"):
                await auth_service.revoke(session, str(payload["sid"]))
        except Unauthenticated:
            pass
    clear_auth_cookies(response)
    response.status_code = 204
    return response


@router.post("/logout/all", status_code=204)
async def logout_all(
    response: Response,
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_db),
) -> Response:
    await auth_service.revoke_all(session, user_id)
    clear_auth_cookies(response)
    response.status_code = 204
    return response


@router.get("/me")
async def me(
    user_id: str = Depends(current_user_id), session: AsyncSession = Depends(get_read_db)
) -> dict:
    user = await session.get(User, user_id)
    if user is None or user.status != "active":
        raise Unauthenticated()
    return {"user": auth_service.serialise_user(user)}
