"""First end-to-end proof: register, browse, order, confirm."""
from app.services import money
from tests.conftest import register_and_login


async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["app"] == "DineMate"


async def test_menu_public(client):
    r = await client.get("/api/menu")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) >= 8
    assert all("price_display" in i for i in items)


async def test_cart_flow(client):
    c = await register_and_login(client, "smoke@dinemate.example")
    r = await c.post("/api/cart/lines", json={"item_id": "r1-m1", "quantity": 2})
    assert r.status_code == 200, r.text
    cart = r.json()["cart"]
    assert cart["lines"][0]["quantity"] == 2

    # Derived from the seeded price and the configured rate: hardcoding a total
    # ties the test to one currency and one tax regime.
    unit = cart["lines"][0]["unit_price_cents"]
    assert cart["subtotal_cents"] == unit * 2
    assert cart["tax_cents"] == money.tax_for(cart["subtotal_cents"])
    assert cart["total_cents"] == cart["subtotal_cents"] + cart["tax_cents"]
    assert cart["total_display"] == money.display(cart["total_cents"])


async def test_confirm_requires_token(client):
    c = await register_and_login(client, "notoken@dinemate.example")
    await c.post("/api/cart/lines", json={"item_id": "r1-m1", "quantity": 1})
    r = await c.post("/api/orders", json={"confirmation_token": "made-up"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "NO_CONFIRMATION"


async def test_full_order(client):
    c = await register_and_login(client, "order@dinemate.example")
    await c.post("/api/cart/lines", json={"item_id": "r1-m1", "quantity": 2})
    await c.post("/api/cart/lines", json={"item_id": "r1-m9", "quantity": 1})

    r = await c.get("/api/cart")
    token = r.json()["confirmation_token"]
    assert token

    r = await c.post(
        "/api/orders",
        json={"confirmation_token": token, "fulfilment": "pickup"},
        headers={"Idempotency-Key": "test-key-1"},
    )
    assert r.status_code == 201, r.text
    order = r.json()["order"]
    assert order["status"] == "confirmed"
    assert order["subtotal_cents"] == sum(l["line_total_cents"] for l in order["lines"])
    assert order["total_cents"] == order["subtotal_cents"] + order["tax_cents"]
    assert order["id"].startswith("ORD-")
