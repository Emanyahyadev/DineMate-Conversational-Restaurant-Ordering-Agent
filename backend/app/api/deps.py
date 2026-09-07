"""Request dependencies. Identity is resolved here and nowhere else."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.postgres import SessionLocal
from app.services import auth_service
from app.services.errors import Unauthenticated

ACCESS_COOKIE = "dm_access"
REFRESH_COOKIE = "dm_refresh"
CSRF_COOKIE = "dm_csrf"
CSRF_HEADER = "X-CSRF-Token"


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def current_user_id(request: Request) -> str:
    """The single source of identity. Never read from the body or the model."""
    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        header = request.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            token = header[7:]
    if not token:
        raise Unauthenticated()
    payload = auth_service.decode_access_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise Unauthenticated()
    return str(user_id)


async def verify_csrf(request: Request) -> None:
    """Double-submit: cookie value must equal the header (AUTH_SPEC section 6)."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    cookie = request.cookies.get(CSRF_COOKIE)
    header = request.headers.get(CSRF_HEADER)
    if not cookie or not header or cookie != header:
        raise Unauthenticated("Your session could not be verified. Please refresh and retry.")


def set_auth_cookies(
    response: Response, *, access: str, refresh: str, csrf: str
) -> None:
    common = {
        "httponly": True,
        "secure": settings.cookie_secure,
        "domain": settings.cookie_domain or None,
    }
    response.set_cookie(
        ACCESS_COOKIE,
        access,
        max_age=settings.access_token_ttl_seconds,
        samesite="lax",
        path="/",
        **common,
    )
    response.set_cookie(
        REFRESH_COOKIE,
        refresh,
        max_age=settings.refresh_token_ttl_days * 86400,
        samesite="strict",
        path="/api/auth",
        **common,
    )
    # Readable by JS on purpose: it is the double-submit value.
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        max_age=settings.refresh_token_ttl_days * 86400,
        samesite="lax",
        path="/",
        httponly=False,
        secure=settings.cookie_secure,
        domain=settings.cookie_domain or None,
    )


def clear_auth_cookies(response: Response) -> None:
    for name, path in (
        (ACCESS_COOKIE, "/"),
        (REFRESH_COOKIE, "/api/auth"),
        (CSRF_COOKIE, "/"),
    ):
        response.delete_cookie(name, path=path, domain=settings.cookie_domain or None)


CurrentUser = Depends(current_user_id)
Db = Depends(get_db)
Csrf = Depends(verify_csrf)
