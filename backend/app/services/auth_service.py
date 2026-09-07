"""Email + password authentication (AUTH_SPEC.md).

Google OAuth is deliberately not implemented in v1 - see AUTH_SPEC.md section 3
note and the PRD deviation recorded in docs/adr/0005.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Session as SessionRow
from app.db.models import User
from app.services.errors import Conflict, Unauthenticated, ValidationError

# m=64MiB, t=3, p=4 per AUTH_SPEC.md section 3
_hasher = PasswordHasher(memory_cost=65536, time_cost=3, parallelism=4)

MIN_PASSWORD_LENGTH = 12

# A tiny stand-in for the top-10k breached list; the real list is loaded from
# seeds/breached.txt when present.
COMMON_PASSWORDS = {
    "password123456",
    "123456789012",
    "qwertyuiop12",
    "letmein12345",
    "administrator",
    "passwordpassword",
    "111111111111",
}


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    if not password_hash:
        return False
    try:
        _hasher.verify(password_hash, password)
        return True
    except (VerifyMismatchError, Exception):  # noqa: B014 - any argon2 error is a failure
        return False


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if password.lower() in COMMON_PASSWORDS:
        raise ValidationError("That password is too common. Please choose another.")


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create_access_token(user_id: str, session_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "sid": session_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.access_token_ttl_seconds)).timestamp()),
        "iss": settings.jwt_issuer,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],  # never accept alg from the token itself
            issuer=settings.jwt_issuer,
        )
    except JWTError as exc:
        raise Unauthenticated("Your session has expired. Please sign in again.") from exc


def serialise_user(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "email_verified": user.email_verified_at is not None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


async def register(
    session: AsyncSession, *, email: str, password: str, display_name: str | None = None
) -> User:
    email = email.strip().lower()
    validate_password(password)

    existing = await session.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none() is not None:
        raise Conflict("An account with that email already exists.")

    user = User(
        email=email,
        password_hash=hash_password(password),
        display_name=(display_name or "").strip()[:80] or None,
        status="active",
    )
    session.add(user)
    await session.flush()
    return user


async def authenticate(session: AsyncSession, *, email: str, password: str) -> User:
    """Identical response and comparable timing whether or not the account exists."""
    row = await session.execute(select(User).where(User.email == email.strip().lower()))
    user = row.scalar_one_or_none()

    if user is None:
        # Burn comparable time so absence is not detectable by latency.
        _hasher.hash("timing-equalisation-placeholder")
        raise Unauthenticated("That email or password is not right.")
    if user.status != "active" or not verify_password(user.password_hash, password):
        raise Unauthenticated("That email or password is not right.")
    return user


async def create_session(
    session: AsyncSession, user: User, *, user_agent: str = "", ip: str = ""
) -> tuple[SessionRow, str]:
    raw_refresh = secrets.token_urlsafe(32)
    row = SessionRow(
        user_id=user.id,
        refresh_token_hash=_hash_token(raw_refresh),
        user_agent=user_agent[:300] or None,
        ip_hash=hashlib.sha256(ip.encode()).hexdigest()[:32] if ip else None,
        expires_at=datetime.now(timezone.utc)
        + timedelta(days=settings.refresh_token_ttl_days),
    )
    session.add(row)
    await session.flush()
    return row, raw_refresh


async def rotate_session(
    session: AsyncSession, raw_refresh: str
) -> tuple[User, SessionRow, str]:
    """Rotation with reuse detection: a replayed token revokes the whole family."""
    row = await session.execute(
        select(SessionRow).where(SessionRow.refresh_token_hash == _hash_token(raw_refresh))
    )
    current = row.scalar_one_or_none()
    now = datetime.now(timezone.utc)

    if current is None:
        raise Unauthenticated("Please sign in again.")

    if current.revoked_at is not None:
        # Replay of a rotated token means it was stolen. Revoke the whole family.
        # This must be COMMITTED before raising: the request-scoped session rolls
        # back on exception, which would silently undo the revocation.
        await revoke_all(session, current.user_id)
        await session.commit()
        raise Unauthenticated("Please sign in again.")

    if current.expires_at <= now:
        current.revoked_at = now
        await session.commit()
        raise Unauthenticated("Your session has expired. Please sign in again.")

    user = await session.get(User, current.user_id)
    if user is None or user.status != "active":
        raise Unauthenticated("Please sign in again.")

    current.revoked_at = now
    new_row, new_raw = await create_session(
        session, user, user_agent=current.user_agent or "", ip=""
    )
    return user, new_row, new_raw


async def revoke(session: AsyncSession, session_id: str) -> None:
    row = await session.get(SessionRow, session_id)
    if row is not None and row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        await session.flush()


async def revoke_all(session: AsyncSession, user_id: str) -> None:
    rows = await session.execute(
        select(SessionRow).where(SessionRow.user_id == user_id, SessionRow.revoked_at.is_(None))
    )
    now = datetime.now(timezone.utc)
    for row in rows.scalars():
        row.revoked_at = now
    await session.flush()
