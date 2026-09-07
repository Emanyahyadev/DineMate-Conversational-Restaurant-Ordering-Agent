"""The confirmation protocol and cancellation window (ADR-0004, Rules L2/L3)."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.models import Order
from app.db.postgres import SessionLocal
from tests.conftest import register_and_login


async def _cart_with_token(c, item="r1-m1", qty=1):
    await c.post("/api/cart/lines", json={"item_id": item, "quantity": qty})
    return (await c.get("/api/cart")).json()["confirmation_token"]


async def test_token_single_use(client):
    c = await register_and_login(client, "single@dinemate.example")
    token = await _cart_with_token(c)
    r1 = await c.post("/api/orders", json={"confirmation_token": token},
                      headers={"Idempotency-Key": "k1"})
    assert r1.status_code == 201
    r2 = await c.post("/api/orders", json={"confirmation_token": token},
                      headers={"Idempotency-Key": "k2"})
    assert r2.status_code == 409


async def test_cart_change_invalidates_token(client):
    """US-15: any mutation forces a fresh read-back."""
    c = await register_and_login(client, "stale@dinemate.example")
    token = await _cart_with_token(c)
    await c.post("/api/cart/lines", json={"item_id": "r1-m5", "quantity": 1})
    r = await c.post("/api/orders", json={"confirmation_token": token},
                     headers={"Idempotency-Key": "k3"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] in ("CART_CHANGED", "NO_CONFIRMATION")


async def test_idempotency_replay_returns_same_order(client):
    """KPI R05: a retried confirm must never double-order."""
    c = await register_and_login(client, "idem@dinemate.example")
    token = await _cart_with_token(c, qty=2)
    h = {"Idempotency-Key": "same-key"}
    r1 = await c.post("/api/orders", json={"confirmation_token": token}, headers=h)
    r2 = await c.post("/api/orders", json={"confirmation_token": token}, headers=h)
    assert r1.status_code == 201
    assert r2.json()["order"]["id"] == r1.json()["order"]["id"]

    async with SessionLocal() as s:
        rows = await s.execute(select(Order))
        assert len(list(rows.scalars())) == 1


async def test_empty_cart_has_no_token(client):
    c = await register_and_login(client, "empty@dinemate.example")
    r = await c.get("/api/cart")
    assert r.json()["confirmation_token"] is None


async def test_cancel_inside_window(client):
    c = await register_and_login(client, "cancel1@dinemate.example")
    token = await _cart_with_token(c)
    order = (await c.post("/api/orders", json={"confirmation_token": token},
                          headers={"Idempotency-Key": "c1"})).json()["order"]
    r = await c.post(f"/api/orders/{order['id']}/cancel", json={"reason": "changed my mind"})
    assert r.status_code == 200
    assert r.json()["order"]["status"] == "cancelled"


async def test_cancel_outside_window_refused(client):
    """Rule L2: 10 minutes, and the boundary is closed."""
    c = await register_and_login(client, "cancel2@dinemate.example")
    token = await _cart_with_token(c)
    order = (await c.post("/api/orders", json={"confirmation_token": token},
                          headers={"Idempotency-Key": "c2"})).json()["order"]

    async with SessionLocal() as s:
        row = await s.get(Order, order["id"])
        row.confirmed_at = datetime.now(timezone.utc) - timedelta(minutes=11)
        await s.commit()

    r = await c.post(f"/api/orders/{order['id']}/cancel", json={})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "CANCELLATION_WINDOW_EXPIRED"


async def test_cancel_once_preparing_refused(client):
    """Rule L3: from preparing on, only staff may cancel."""
    c = await register_and_login(client, "cancel3@dinemate.example")
    token = await _cart_with_token(c)
    order = (await c.post("/api/orders", json={"confirmation_token": token},
                          headers={"Idempotency-Key": "c3"})).json()["order"]

    from app.config import settings
    r = await c.post(
        f"/internal/orders/{order['id']}/status",
        json={"to_status": "preparing", "actor": "staff"},
        headers={"X-Internal-Secret": settings.internal_secret},
    )
    assert r.status_code == 200

    r = await c.post(f"/api/orders/{order['id']}/cancel", json={})
    assert r.status_code == 409


async def test_illegal_transition_rejected(client):
    c = await register_and_login(client, "trans@dinemate.example")
    token = await _cart_with_token(c)
    order = (await c.post("/api/orders", json={"confirmation_token": token},
                          headers={"Idempotency-Key": "c4"})).json()["order"]

    from app.config import settings
    # confirmed -> completed is not a legal edge (Rule L1)
    r = await c.post(
        f"/internal/orders/{order['id']}/status",
        json={"to_status": "completed", "actor": "staff"},
        headers={"X-Internal-Secret": settings.internal_secret},
    )
    assert r.status_code == 409


async def test_internal_endpoint_needs_secret(client):
    r = await client.post("/internal/orders/ORD-000001/status",
                          json={"to_status": "preparing", "actor": "staff"})
    assert r.status_code == 401
