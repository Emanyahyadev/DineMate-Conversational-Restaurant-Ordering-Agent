"""AUTH_SPEC.md section 7 attack posture."""
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import auth_service
from tests.conftest import register_and_login

PW = "correct-horse-battery"


async def test_password_minimum_enforced(client):
    r = await client.post(
        "/api/auth/register", json={"email": "short@dinemate.example", "password": "short"}
    )
    assert r.status_code == 400


async def test_no_enumeration_oracle_on_login(client):
    await register_and_login(client, "known@dinemate.example")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        wrong_pw = await c.post(
            "/api/auth/login", json={"email": "known@dinemate.example", "password": "wrong-password-x"}
        )
        no_user = await c.post(
            "/api/auth/login", json={"email": "nobody@dinemate.example", "password": "wrong-password-x"}
        )
    assert wrong_pw.status_code == no_user.status_code == 401
    # request_id differs by design; the customer-visible parts must not.
    a, b = wrong_pw.json()["error"], no_user.json()["error"]
    assert (a["code"], a["message"]) == (b["code"], b["message"])


async def test_duplicate_registration_conflicts(client):
    await register_and_login(client, "dupe@dinemate.example")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/auth/register", json={"email": "dupe@dinemate.example", "password": PW})
    assert r.status_code == 409


async def test_tampered_jwt_rejected(client):
    c = await register_and_login(client, "tamper@dinemate.example")
    good = c.cookies.get("dm_access")
    c.cookies.set("dm_access", good[:-4] + "AAAA")
    r = await c.get("/api/auth/me")
    assert r.status_code == 401


async def test_alg_none_jwt_rejected(client):
    """A classic: a token signed with 'none' must never be accepted."""
    import base64, json

    header = base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode()).rstrip(b"=")
    payload = base64.urlsafe_b64encode(
        json.dumps({"sub": "attacker", "sid": "x", "iss": "dinemate", "exp": 9999999999}).encode()
    ).rstrip(b"=")
    forged = f"{header.decode()}.{payload.decode()}."
    client.cookies.set("dm_access", forged)
    r = await client.get("/api/auth/me")
    assert r.status_code == 401


async def test_csrf_required_on_mutations(client):
    c = await register_and_login(client, "csrf@dinemate.example")
    del c.headers["X-CSRF-Token"]
    r = await c.post("/api/cart/lines", json={"item_id": "r1-m1", "quantity": 1})
    assert r.status_code == 401


async def test_refresh_rotation_and_reuse_detection(client):
    c = await register_and_login(client, "rotate@dinemate.example")
    first = c.cookies.get("dm_refresh")

    r = await c.post("/api/auth/refresh")
    assert r.status_code == 200
    second = c.cookies.get("dm_refresh")
    assert second != first, "refresh token must rotate"

    # Replaying the old token means it was stolen: kill the whole family.
    c.cookies.set("dm_refresh", first)
    r = await c.post("/api/auth/refresh")
    assert r.status_code == 401

    c.cookies.set("dm_refresh", second)
    r = await c.post("/api/auth/refresh")
    assert r.status_code == 401, "reuse must revoke every session in the family"


async def test_logout_revokes_session(client):
    c = await register_and_login(client, "logout@dinemate.example")
    assert (await c.get("/api/auth/me")).status_code == 200
    await c.post("/api/auth/logout")
    r = await c.get("/api/auth/me")
    assert r.status_code == 401


def test_password_hash_is_argon2id():
    h = auth_service.hash_password(PW)
    assert h.startswith("$argon2id$")
    assert auth_service.verify_password(h, PW)
    assert not auth_service.verify_password(h, PW + "x")
    assert not auth_service.verify_password(None, PW)
