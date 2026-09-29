"""INV-1..INV-10 against a live database (DATA_MODEL.md section 8)."""
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.db.models import Cart, Order, OrderEvent, OrderLine
from app.db.postgres import SessionLocal
from app.services import cart_service
from app.services.errors import ItemNotFound, QuantityOutOfRange
from tests.conftest import register_and_login


async def _user(client, email):
    c = await register_and_login(client, email)
    me = (await c.get("/api/auth/me")).json()["user"]
    return c, me["id"]


async def test_inv1_item_must_exist(client):
    _, uid = await _user(client, "inv1@dinemate.example")
    async with SessionLocal() as s:
        with pytest.raises(ItemNotFound):
            await cart_service.add_line(s, uid, item_id="does-not-exist")


async def test_inv2_quantity_bounds(client):
    _, uid = await _user(client, "inv2@dinemate.example")
    async with SessionLocal() as s:
        with pytest.raises(QuantityOutOfRange):
            await cart_service.add_line(s, uid, item_id="r1-m1", quantity=21)
        with pytest.raises(QuantityOutOfRange):
            await cart_service.add_line(s, uid, item_id="r1-m1", quantity=0)


async def test_inv2_enforced_by_database(client):
    """Not just the service: the CHECK constraint must hold too."""
    c, uid = await _user(client, "inv2db@dinemate.example")
    await c.post("/api/cart/lines", json={"item_id": "r1-m1", "quantity": 1})
    async with SessionLocal() as s:
        with pytest.raises((IntegrityError, DBAPIError)):
            await s.execute(text("UPDATE cart_lines SET quantity = 99"))
            await s.commit()


async def test_inv3_one_open_cart_per_user(client):
    c, uid = await _user(client, "inv3@dinemate.example")
    await c.post("/api/cart/lines", json={"item_id": "r1-m1", "quantity": 1})
    async with SessionLocal() as s:
        with pytest.raises((IntegrityError, DBAPIError)):
            s.add(Cart(user_id=uid, status="open", version=0))
            await s.commit()


async def test_inv4_total_consistency_enforced(client):
    c, _ = await _user(client, "inv4@dinemate.example")
    await c.post("/api/cart/lines", json={"item_id": "r1-m1", "quantity": 2})
    token = (await c.get("/api/cart")).json()["confirmation_token"]
    await c.post("/api/orders", json={"confirmation_token": token, "contact_phone": "03001234567"},
                 headers={"Idempotency-Key": "inv4"})
    async with SessionLocal() as s:
        with pytest.raises((IntegrityError, DBAPIError)):
            await s.execute(text("UPDATE orders SET total = total + 500"))
            await s.commit()


async def test_inv4_line_total_consistency_enforced(client):
    c, _ = await _user(client, "inv4b@dinemate.example")
    await c.post("/api/cart/lines", json={"item_id": "r1-m1", "quantity": 2})
    token = (await c.get("/api/cart")).json()["confirmation_token"]
    await c.post("/api/orders", json={"confirmation_token": token, "contact_phone": "03001234567"},
                 headers={"Idempotency-Key": "inv4b"})
    async with SessionLocal() as s:
        with pytest.raises((IntegrityError, DBAPIError)):
            await s.execute(text("UPDATE order_lines SET line_total = 1"))
            await s.commit()


async def test_inv5_and_inv6_order_has_lines_and_events(client):
    c, _ = await _user(client, "inv56@dinemate.example")
    await c.post("/api/cart/lines", json={"item_id": "r1-m1", "quantity": 1})
    token = (await c.get("/api/cart")).json()["confirmation_token"]
    await c.post("/api/orders", json={"confirmation_token": token, "contact_phone": "03001234567"},
                 headers={"Idempotency-Key": "inv56"})
    async with SessionLocal() as s:
        order = (await s.execute(select(Order))).scalar_one()
        lines = (await s.execute(select(OrderLine).where(OrderLine.order_id == order.id))).scalars()
        events = (await s.execute(select(OrderEvent).where(OrderEvent.order_id == order.id))).scalars()
        assert len(list(lines)) >= 1   # INV-5
        assert len(list(events)) >= 1  # INV-6


async def test_confirm_is_atomic_on_failure(client):
    """Rule R1: an unavailable item at confirm time leaves nothing behind."""
    c, _ = await _user(client, "atomic@dinemate.example")
    await c.post("/api/cart/lines", json={"item_id": "r1-m1", "quantity": 1})
    token = (await c.get("/api/cart")).json()["confirmation_token"]

    async with SessionLocal() as s:
        await s.execute(text("UPDATE menu_items SET is_available = false WHERE id = 'r1-m1'"))
        await s.commit()
    try:
        r = await c.post("/api/orders", json={"confirmation_token": token, "contact_phone": "03001234567"},
                         headers={"Idempotency-Key": "atomic"})
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "ITEM_UNAVAILABLE"
        async with SessionLocal() as s:
            assert list((await s.execute(select(Order))).scalars()) == []
    finally:
        async with SessionLocal() as s:
            await s.execute(text("UPDATE menu_items SET is_available = true WHERE id = 'r1-m1'"))
            await s.commit()
        from app.services import menu_service
        menu_service.invalidate_cache()


async def test_inv8_no_order_without_consumed_token(client):
    c, _ = await _user(client, "inv8@dinemate.example")
    await c.post("/api/cart/lines", json={"item_id": "r1-m1", "quantity": 1})
    token = (await c.get("/api/cart")).json()["confirmation_token"]
    await c.post("/api/orders", json={"confirmation_token": token, "contact_phone": "03001234567"},
                 headers={"Idempotency-Key": "inv8"})
    from app.cli import check_invariants
    assert await check_invariants() == 0


async def test_cart_merges_identical_lines(client):
    """Rule C1."""
    c, _ = await _user(client, "merge@dinemate.example")
    await c.post("/api/cart/lines", json={"item_id": "r1-m1", "quantity": 1})
    r = await c.post("/api/cart/lines", json={"item_id": "r1-m1", "quantity": 2})
    cart = r.json()["cart"]
    assert len(cart["lines"]) == 1
    assert cart["lines"][0]["quantity"] == 3


async def test_update_sets_quantity_not_increments(client):
    """US-09: the failure mode where 'make it three' yields five."""
    c, _ = await _user(client, "setqty@dinemate.example")
    r = await c.post("/api/cart/lines", json={"item_id": "r1-m1", "quantity": 2})
    line_id = r.json()["cart"]["lines"][0]["line_id"]
    r = await c.patch(f"/api/cart/lines/{line_id}", json={"quantity": 3})
    assert r.json()["cart"]["lines"][0]["quantity"] == 3


async def test_update_to_zero_removes(client):
    c, _ = await _user(client, "zeroqty@dinemate.example")
    r = await c.post("/api/cart/lines", json={"item_id": "r1-m1", "quantity": 2})
    line_id = r.json()["cart"]["lines"][0]["line_id"]
    r = await c.patch(f"/api/cart/lines/{line_id}", json={"quantity": 0})
    assert r.json()["cart"]["lines"] == []
