"""An order must contain what the cart contained. Nothing else.

A kitchen ticket that does not match what the customer asked for is the worst
failure this system has: the customer is charged for food they did not order and
the restaurant cooks the wrong thing. US-15 defends it with a cart version on
the confirmation token, and these hold that line.
"""

from tests.conftest import register_and_login


async def read_back(c):
    """What view_cart would issue: the token for the cart as it stands."""
    return (await c.get("/api/cart")).json()["confirmation_token"]


async def test_the_order_contains_exactly_what_was_in_the_cart(client):
    c = await register_and_login(client, "match1@dinemate.example")
    await c.post("/api/cart/lines", json={"item_id": "r1-m1", "quantity": 1})
    token = await read_back(c)

    order = (
        await c.post(
            "/api/orders",
            json={"confirmation_token": token, "contact_phone": "03001234567"},
            headers={"Idempotency-Key": "match-1"},
        )
    ).json()["order"]

    assert [(l["name"], l["quantity"]) for l in order["lines"]] == [("Chicken Charga", 1)]


async def test_a_token_issued_before_an_add_is_refused(client):
    """The exact shape of a stale-token order: read back, then add, then confirm."""
    c = await register_and_login(client, "match2@dinemate.example")
    await c.post("/api/cart/lines", json={"item_id": "r1-m9", "quantity": 1})
    stale = await read_back(c)

    # The customer changes their mind and adds something else.
    await c.post("/api/cart/lines", json={"item_id": "r1-m1", "quantity": 1})

    r = await c.post(
        "/api/orders",
        json={"confirmation_token": stale, "contact_phone": "03001234567"},
        headers={"Idempotency-Key": "match-2"},
    )
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "CART_CHANGED"


async def test_a_token_issued_before_a_removal_is_refused(client):
    c = await register_and_login(client, "match3@dinemate.example")
    await c.post("/api/cart/lines", json={"item_id": "r1-m1", "quantity": 1})
    await c.post("/api/cart/lines", json={"item_id": "r1-m9", "quantity": 1})
    stale = await read_back(c)

    lines = (await c.get("/api/cart")).json()["cart"]["restaurants"][0]["lines"]
    await c.delete(f"/api/cart/lines/{lines[0]['line_id']}")

    r = await c.post(
        "/api/orders",
        json={"confirmation_token": stale, "contact_phone": "03001234567"},
        headers={"Idempotency-Key": "match-3"},
    )
    assert r.status_code == 409


async def test_a_token_issued_before_the_cart_was_emptied_is_refused(client):
    """The Fresh Lime Soda case: clear the cart, order something else, confirm."""
    c = await register_and_login(client, "match4@dinemate.example")
    await c.post("/api/cart/lines", json={"item_id": "r1-m9", "quantity": 1})
    stale = await read_back(c)

    await c.delete("/api/cart")
    await c.post("/api/cart/lines", json={"item_id": "r1-m1", "quantity": 1})

    r = await c.post(
        "/api/orders",
        json={"confirmation_token": stale, "contact_phone": "03001234567"},
        headers={"Idempotency-Key": "match-4"},
    )
    assert r.status_code == 409, (
        "a token from an abandoned cart placed an order for the wrong dish"
    )


async def test_a_consumed_token_cannot_be_used_again(client):
    c = await register_and_login(client, "match5@dinemate.example")
    await c.post("/api/cart/lines", json={"item_id": "r1-m1", "quantity": 1})
    token = await read_back(c)

    first = await c.post(
        "/api/orders",
        json={"confirmation_token": token, "contact_phone": "03001234567"},
        headers={"Idempotency-Key": "match-5a"},
    )
    assert first.status_code == 201

    replay = await c.post(
        "/api/orders",
        json={"confirmation_token": token, "contact_phone": "03001234567"},
        headers={"Idempotency-Key": "match-5b"},
    )
    assert replay.status_code in (400, 409)


async def test_a_customer_has_only_one_open_cart(client):
    """Two open carts would let a token point at the one nobody is looking at."""
    from sqlalchemy import func, select

    from app.db.models import Cart
    from app.db.postgres import SessionLocal

    c = await register_and_login(client, "match6@dinemate.example")
    me = (await c.get("/api/auth/me")).json()["user"]

    for item in ("r1-m1", "r1-m9", "r3-m1"):
        await c.post("/api/cart/lines", json={"item_id": item, "quantity": 1})
        await c.get("/api/cart")

    async with SessionLocal() as s:
        open_carts = await s.execute(
            select(func.count(Cart.id)).where(
                Cart.user_id == me["id"], Cart.status == "open"
            )
        )
        assert open_carts.scalar() == 1
