"""A tool or route may only ever touch the caller's own rows (KPI A03, hard gate).

User B attempts every owner-scoped resource belonging to user A and must get
NOT_FOUND - never FORBIDDEN, which would confirm the resource exists (US-18).
"""
import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.conftest import register_and_login


async def _fresh_client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed_user_a():
    """User A with a cart, a confirmed order and a conversation."""
    async with await _fresh_client() as a:
        await register_and_login(a, "alice@dinemate.example")
        await a.post("/api/cart/lines", json={"item_id": "r1-m1", "quantity": 2})
        token = (await a.get("/api/cart")).json()["confirmation_token"]
        order = (
            await a.post(
                "/api/orders",
                json={"confirmation_token": token},
                headers={"Idempotency-Key": "alice-1"},
            )
        ).json()["order"]

        async with a.stream("POST", "/api/chat", json={"message": "hello"}) as r:
            conv = None
            name = None
            async for line in r.aiter_lines():
                if line.startswith("event:"):
                    name = line.split(":", 1)[1].strip()
                elif line.startswith("data:") and name == "start":
                    conv = json.loads(line.split(":", 1)[1].strip())["conversation_id"]
                    break
        return {"order_id": order["id"], "conversation_id": conv, "total": order["total_cents"]}


@pytest.fixture
async def alice_data():
    return await _seed_user_a()


async def test_foreign_order_is_not_found(client, alice_data):
    b = await register_and_login(client, "bob@dinemate.example")
    r = await b.get(f"/api/orders/{alice_data['order_id']}")
    assert r.status_code == 404
    assert r.json()["error"]["code"] in ("NOT_FOUND", "ORDER_NOT_FOUND")
    assert alice_data["order_id"] not in r.text
    assert str(alice_data["total"]) not in r.text


async def test_foreign_order_cancel_is_not_found(client, alice_data):
    b = await register_and_login(client, "bob2@dinemate.example")
    r = await b.post(f"/api/orders/{alice_data['order_id']}/cancel", json={})
    assert r.status_code == 404


async def test_foreign_conversation_is_not_found(client, alice_data):
    b = await register_and_login(client, "bob3@dinemate.example")
    r = await b.get(f"/api/conversations/{alice_data['conversation_id']}")
    assert r.status_code == 404


async def test_foreign_conversation_delete_is_not_found(client, alice_data):
    b = await register_and_login(client, "bob4@dinemate.example")
    r = await b.delete(f"/api/conversations/{alice_data['conversation_id']}")
    assert r.status_code == 404


async def test_b_sees_own_empty_cart_not_alices(client, alice_data):
    b = await register_and_login(client, "bob5@dinemate.example")
    r = await b.get("/api/cart")
    assert r.json()["cart"]["lines"] == []


async def test_b_order_list_excludes_alices(client, alice_data):
    b = await register_and_login(client, "bob6@dinemate.example")
    r = await b.get("/api/orders")
    assert r.json()["items"] == []


async def test_agent_cannot_reach_a_foreign_order(client, alice_data):
    """The tool path, not just the REST path."""
    b = await register_and_login(client, "bob7@dinemate.example")
    reply = ""
    async with b.stream(
        "POST", "/api/chat", json={"message": f"where is my order {alice_data['order_id']}?"}
    ) as r:
        name = None
        async for line in r.aiter_lines():
            if line.startswith("event:"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("data:") and name == "token":
                reply += json.loads(line.split(":", 1)[1].strip())["delta"]
    assert str(alice_data["total"]) not in reply
    assert "confirmed" not in reply.lower()


async def test_unauthenticated_is_401_everywhere(client):
    for method, path in [
        ("get", "/api/cart"),
        ("get", "/api/orders"),
        ("get", "/api/profile"),
        ("get", "/api/profile/memories"),
        ("get", "/api/conversations"),
        ("get", "/api/auth/me"),
    ]:
        r = await getattr(client, method)(path)
        assert r.status_code == 401, f"{method} {path} returned {r.status_code}"
