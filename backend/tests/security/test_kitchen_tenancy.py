"""One kitchen sees its own orders and nobody else's.

This is the customer ownership rule one level up: staff identity comes from the
account, no route takes a restaurant_id, and a customer cannot reach any of it.
"""

from app.db.models import User
from app.db.postgres import SessionLocal
from tests.conftest import register_and_login


async def make_staff(email: str, restaurant_id: str, client):
    """Register through the API, then promote in the database."""
    c = await register_and_login(client, email)
    me = (await c.get("/api/auth/me")).json()["user"]
    async with SessionLocal() as s:
        user = await s.get(User, me["id"])
        user.role = "staff"
        user.staff_restaurant_id = restaurant_id
        await s.commit()
    return c


async def place_order(c, item_id):
    await c.post("/api/cart/lines", json={"item_id": item_id, "quantity": 1})
    token = (await c.get("/api/cart")).json()["confirmation_token"]
    r = await c.post(
        "/api/orders",
        json={"confirmation_token": token, "contact_phone": "03001234567"},
        headers={"Idempotency-Key": f"k-{item_id}"},
    )
    assert r.status_code == 201, r.text
    return r.json()["order"]


async def test_a_customer_cannot_reach_the_kitchen(client):
    """Not 403: a customer has no business learning this exists."""
    c = await register_and_login(client, "just-a-customer@dinemate.example")
    for path in ("/api/kitchen/me", "/api/kitchen/orders", "/api/kitchen/menu"):
        r = await c.get(path)
        assert r.status_code == 404, f"{path} -> {r.status_code}"


async def test_signed_out_is_unauthenticated(client):
    r = await client.get("/api/kitchen/orders")
    assert r.status_code == 401


async def test_staff_see_their_own_restaurant(client):
    c = await make_staff("chef-a@dinemate.example", "r1", client)
    r = await c.get("/api/kitchen/me")
    assert r.status_code == 200
    assert r.json()["restaurant"]["id"] == "r1"
    assert r.json()["restaurant"]["name"] == "Lahori Charga House"


async def test_a_kitchen_only_sees_its_own_orders(client):
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    # A customer orders from Sindhi Biryani Co (r3).
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as diner:
        d = await register_and_login(diner, "hungry@dinemate.example")
        order = await place_order(d, "r3-m1")

    lahore = await make_staff("chef-b@dinemate.example", "r1", client)
    seen = (await lahore.get("/api/kitchen/orders")).json()["items"]
    assert order["id"] not in [o["id"] for o in seen], "another kitchen's ticket leaked"

    # And it cannot be advanced from the wrong kitchen either.
    r = await lahore.post(
        f"/api/kitchen/orders/{order['id']}/advance", json={"to_status": "preparing"}
    )
    assert r.status_code == 404


async def test_the_right_kitchen_sees_and_advances_the_ticket(client):
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as diner:
        d = await register_and_login(diner, "hungry2@dinemate.example")
        order = await place_order(d, "r3-m2")

    sindhi = await make_staff("chef-c@dinemate.example", "r3", client)
    queue = (await sindhi.get("/api/kitchen/orders")).json()
    ids = [o["id"] for o in queue["items"]]
    assert order["id"] in ids
    assert queue["stats"]["orders_today"] >= 1

    r = await sindhi.post(
        f"/api/kitchen/orders/{order['id']}/advance", json={"to_status": "preparing"}
    )
    assert r.status_code == 200
    assert r.json()["order"]["status"] == "preparing"


async def test_an_illegal_transition_is_still_refused(client):
    """Rule L1 does not relax because staff asked."""
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as diner:
        d = await register_and_login(diner, "hungry3@dinemate.example")
        order = await place_order(d, "r3-m3")

    sindhi = await make_staff("chef-d@dinemate.example", "r3", client)
    r = await sindhi.post(
        f"/api/kitchen/orders/{order['id']}/advance", json={"to_status": "completed"}
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "INVALID_TRANSITION"


async def test_86ing_a_dish_removes_it_from_the_customer_menu(client):
    sindhi = await make_staff("chef-e@dinemate.example", "r3", client)

    r = await sindhi.patch("/api/kitchen/menu/r3-m1", json={"is_available": False})
    assert r.status_code == 200
    assert r.json()["item"]["is_available"] is False

    try:
        public = (await client.get("/api/menu?restaurant_id=r3")).json()["items"]
        assert "Chicken Sindhi Biryani" not in [i["name"] for i in public]
    finally:
        await sindhi.patch("/api/kitchen/menu/r3-m1", json={"is_available": True})


async def test_a_kitchen_cannot_86_another_kitchens_dish(client):
    lahore = await make_staff("chef-f@dinemate.example", "r1", client)
    r = await lahore.patch("/api/kitchen/menu/r3-m1", json={"is_available": False})
    assert r.status_code == 404
