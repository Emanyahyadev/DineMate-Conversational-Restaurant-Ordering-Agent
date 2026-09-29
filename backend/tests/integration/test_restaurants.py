"""Multi-restaurant marketplace and Rule K1: one order, one kitchen."""
from tests.conftest import register_and_login


async def test_restaurants_listed(client):
    r = await client.get("/api/restaurants")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 5
    names = {i["name"] for i in items}
    assert {"Lahori Charga House", "Karachi Seekh & Broast", "Sindhi Biryani Co", "Peshawari Namak Mandi", "Chai Khana"} == names
    for i in items:
        assert i["item_count"] >= 8
        assert i["cuisine"]


async def test_menu_carries_its_restaurant(client):
    r = await client.get("/api/menu")
    for item in r.json()["items"]:
        assert item["restaurant_id"]
        assert item["restaurant_name"]


async def test_menu_filters_by_restaurant(client):
    r = await client.get("/api/menu?restaurant_id=r3")
    items = r.json()["items"]
    assert items
    assert {i["restaurant_id"] for i in items} == {"r3"}
    assert any(i["name"] == "Chicken Sindhi Biryani" for i in items)


async def test_a_dish_type_can_exist_in_two_kitchens(client):
    """The unique name index is per restaurant, not global: several kitchens
    serve naan, and each one is its own row."""
    r = await client.get("/api/menu?q=naan")
    items = r.json()["items"]
    assert len(items) > 1
    assert len({i["restaurant_id"] for i in items}) > 1


async def test_a_basket_may_span_kitchens(client):
    """No gate: a customer can want biryani and chai in the same sitting."""
    c = await register_and_login(client, "kitchen1@dinemate.example")
    await c.post("/api/cart/lines", json={"item_id": "r3-m1", "quantity": 1})
    r = await c.post("/api/cart/lines", json={"item_id": "r5-m1", "quantity": 2})

    assert r.status_code == 200
    cart = r.json()["cart"]
    assert cart["restaurant_count"] == 2
    assert {g["restaurant_name"] for g in cart["restaurants"]} == {
        "Sindhi Biryani Co",
        "Chai Khana",
    }
    assert len(cart["lines"]) == 2


async def test_each_kitchen_group_carries_its_own_subtotal(client):
    """The customer sees what each kitchen costs before committing."""
    c = await register_and_login(client, "kitchen2@dinemate.example")
    await c.post("/api/cart/lines", json={"item_id": "r3-m1", "quantity": 2})
    r = await c.post("/api/cart/lines", json={"item_id": "r5-m1", "quantity": 1})

    cart = r.json()["cart"]
    by_name = {g["restaurant_name"]: g for g in cart["restaurants"]}
    assert by_name["Sindhi Biryani Co"]["subtotal_cents"] == 550 * 2
    assert by_name["Chai Khana"]["subtotal_cents"] == 150
    assert cart["subtotal_cents"] == sum(
        g["subtotal_cents"] for g in cart["restaurants"]
    )


async def test_checkout_splits_into_one_order_per_kitchen(client):
    """Each kitchen cooks on its own clock, so each gets its own ticket."""
    c = await register_and_login(client, "kitchen3@dinemate.example")
    await c.post("/api/cart/lines", json={"item_id": "r3-m1", "quantity": 1})
    await c.post("/api/cart/lines", json={"item_id": "r5-m6", "quantity": 2})
    token = (await c.get("/api/cart")).json()["confirmation_token"]

    r = await c.post(
        "/api/orders",
        json={"confirmation_token": token, "contact_phone": "03001234567"},
        headers={"Idempotency-Key": "split-1"},
    )
    assert r.status_code == 201
    orders = r.json()["orders"]
    assert len(orders) == 2

    # Tied together as one checkout, but independently workable.
    assert len({o["order_group_id"] for o in orders}) == 1
    assert {o["restaurant_name"] for o in orders} == {
        "Sindhi Biryani Co",
        "Chai Khana",
    }
    for o in orders:
        assert o["status"] == "confirmed"
        assert o["total_cents"] == o["subtotal_cents"] + o["tax_cents"]
        assert len(o["lines"]) >= 1

    assert (await c.get("/api/cart")).json()["cart"]["lines"] == []


async def test_a_split_checkout_is_still_replay_safe(client):
    """KPI R05: retrying must not double any of the orders."""
    c = await register_and_login(client, "kitchen4@dinemate.example")
    await c.post("/api/cart/lines", json={"item_id": "r3-m1", "quantity": 1})
    await c.post("/api/cart/lines", json={"item_id": "r5-m1", "quantity": 1})
    token = (await c.get("/api/cart")).json()["confirmation_token"]

    h = {"Idempotency-Key": "split-replay"}
    first = await c.post("/api/orders", json={"confirmation_token": token, "contact_phone": "03001234567"}, headers=h)
    second = await c.post("/api/orders", json={"confirmation_token": token, "contact_phone": "03001234567"}, headers=h)

    assert first.status_code == 201
    assert {o["id"] for o in second.json()["orders"]} == {
        o["id"] for o in first.json()["orders"]
    }
    assert len((await c.get("/api/orders")).json()["items"]) == 2


async def test_each_split_order_is_cancelled_on_its_own(client):
    """Changing your mind about the chai leaves the biryani cooking."""
    c = await register_and_login(client, "kitchen5@dinemate.example")
    await c.post("/api/cart/lines", json={"item_id": "r3-m1", "quantity": 1})
    await c.post("/api/cart/lines", json={"item_id": "r5-m1", "quantity": 1})
    token = (await c.get("/api/cart")).json()["confirmation_token"]
    orders = (
        await c.post(
            "/api/orders",
            json={"confirmation_token": token, "contact_phone": "03001234567"},
            headers={"Idempotency-Key": "split-cancel"},
        )
    ).json()["orders"]

    chai = next(o for o in orders if o["restaurant_name"] == "Chai Khana")
    biryani = next(o for o in orders if o["restaurant_name"] == "Sindhi Biryani Co")

    assert (await c.post(f"/api/orders/{chai['id']}/cancel", json={})).status_code == 200
    still = (await c.get(f"/api/orders/{biryani['id']}")).json()["order"]
    assert still["status"] == "confirmed"


async def test_a_kitchen_only_sees_its_half_of_a_split_order(client):
    """The split is what keeps each dashboard honest."""
    from app.db.models import User
    from app.db.postgres import SessionLocal

    c = await register_and_login(client, "kitchen6@dinemate.example")
    await c.post("/api/cart/lines", json={"item_id": "r3-m1", "quantity": 1})
    await c.post("/api/cart/lines", json={"item_id": "r5-m1", "quantity": 1})
    token = (await c.get("/api/cart")).json()["confirmation_token"]
    orders = (
        await c.post(
            "/api/orders",
            json={"confirmation_token": token, "contact_phone": "03001234567"},
            headers={"Idempotency-Key": "split-kitchen"},
        )
    ).json()["orders"]

    me = (await c.get("/api/auth/me")).json()["user"]
    async with SessionLocal() as s:
        user = await s.get(User, me["id"])
        user.role = "staff"
        user.staff_restaurant_id = "r5"  # Chai Khana only
        await s.commit()

    queue = (await c.get("/api/kitchen/orders")).json()["items"]
    ids = {o["id"] for o in queue}
    chai = next(o for o in orders if o["restaurant_id"] == "r5")
    biryani = next(o for o in orders if o["restaurant_id"] == "r3")
    assert chai["id"] in ids
    assert biryani["id"] not in ids


async def test_order_snapshots_the_restaurant(client):
    c = await register_and_login(client, "kitchen5@dinemate.example")
    await c.post("/api/cart/lines", json={"item_id": "r3-m1", "quantity": 2})
    token = (await c.get("/api/cart")).json()["confirmation_token"]
    r = await c.post(
        "/api/orders",
        json={"confirmation_token": token, "contact_phone": "03001234567"},
        headers={"Idempotency-Key": "kitchen-5"},
    )
    order = r.json()["order"]
    assert order["restaurant_id"] == "r3"
    assert order["restaurant_name"] == "Sindhi Biryani Co"


async def test_allergen_filter_spans_all_kitchens(client):
    """A peanut allergy must exclude Sindhi Biryani Co's satay and papaya salad too."""
    r = await client.get("/api/menu?exclude_allergens=peanut")
    for item in r.json()["items"]:
        assert "peanut" not in item["allergens"]


async def test_checkout_requires_a_phone_number(client):
    """The kitchen has to be able to call about the order."""
    c = await register_and_login(client, "nophone@dinemate.example")
    await c.post("/api/cart/lines", json={"item_id": "r3-m1", "quantity": 1})
    token = (await c.get("/api/cart")).json()["confirmation_token"]

    r = await c.post(
        "/api/orders",
        json={"confirmation_token": token},
        headers={"Idempotency-Key": "no-phone"},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_delivery_requires_an_address(client):
    c = await register_and_login(client, "noaddr@dinemate.example")
    await c.post("/api/cart/lines", json={"item_id": "r3-m1", "quantity": 1})
    token = (await c.get("/api/cart")).json()["confirmation_token"]

    r = await c.post(
        "/api/orders",
        json={
            "confirmation_token": token,
            "fulfilment": "delivery",
            "contact_phone": "03001234567",
        },
        headers={"Idempotency-Key": "no-addr"},
    )
    assert r.status_code == 400


async def test_delivery_is_charged_per_kitchen(client):
    """Each kitchen sends its own rider, so each order carries its own fee."""
    from app.config import settings

    c = await register_and_login(client, "delivery@dinemate.example")
    await c.post("/api/cart/lines", json={"item_id": "r3-m1", "quantity": 1})
    await c.post("/api/cart/lines", json={"item_id": "r5-m1", "quantity": 1})
    token = (await c.get("/api/cart")).json()["confirmation_token"]

    orders = (
        await c.post(
            "/api/orders",
            json={
                "confirmation_token": token,
                "fulfilment": "delivery",
                "contact_phone": "03001234567",
                "delivery_address": "House 12, Street 4, Gulberg III, Lahore",
            },
            headers={"Idempotency-Key": "delivery-fee"},
        )
    ).json()["orders"]

    assert len(orders) == 2
    for o in orders:
        assert o["fulfilment"] == "delivery"
        assert o["delivery_fee_cents"] == settings.delivery_fee
        assert o["total_cents"] == o["subtotal_cents"] + o["tax_cents"] + settings.delivery_fee
        assert o["delivery_address"].startswith("House 12")


async def test_contact_details_are_remembered_for_next_time(client):
    """US-24 in spirit: do not ask a returning customer twice."""
    c = await register_and_login(client, "remembered@dinemate.example")
    await c.post("/api/cart/lines", json={"item_id": "r3-m1", "quantity": 1})
    token = (await c.get("/api/cart")).json()["confirmation_token"]
    await c.post(
        "/api/orders",
        json={
            "confirmation_token": token,
            "fulfilment": "delivery",
            "contact_phone": "03009998877",
            "delivery_address": "Flat 3, Askari 11, Lahore",
        },
        headers={"Idempotency-Key": "remember-me"},
    )

    contact = (await c.get("/api/cart")).json()["contact"]
    assert contact["phone"] == "03009998877"
    assert contact["address"] == "Flat 3, Askari 11, Lahore"


async def test_pickup_stores_no_address(client):
    """A collected order has no delivery address to leak."""
    c = await register_and_login(client, "pickup@dinemate.example")
    await c.post("/api/cart/lines", json={"item_id": "r3-m1", "quantity": 1})
    token = (await c.get("/api/cart")).json()["confirmation_token"]
    orders = (
        await c.post(
            "/api/orders",
            json={
                "confirmation_token": token,
                "fulfilment": "pickup",
                "contact_phone": "03001234567",
                "delivery_address": "ignored for collection",
            },
            headers={"Idempotency-Key": "pickup-only"},
        )
    ).json()["orders"]

    assert orders[0]["delivery_address"] == ""
    assert orders[0]["delivery_fee_cents"] == 0
