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


async def test_cart_adopts_the_first_restaurant(client):
    c = await register_and_login(client, "kitchen1@dinemate.example")
    # Chicken Seekh Kabab belongs to Karachi Seekh & Broast (r2).
    r = await c.post(
        "/api/cart/lines",
        json={"item_id": "r2-m2", "quantity": 1},  # Beef Seekh, no option group
    )
    cart = r.json()["cart"]
    assert cart["restaurant_id"] == "r2"
    assert cart["restaurant_name"] == "Karachi Seekh & Broast"


async def test_mixing_kitchens_is_refused(client):
    """Rule K1 - one order cannot be cooked in two places."""
    c = await register_and_login(client, "kitchen2@dinemate.example")
    await c.post("/api/cart/lines", json={"item_id": "r1-m1", "quantity": 1})
    r = await c.post("/api/cart/lines", json={"item_id": "r4-m2", "quantity": 1})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "MIXED_RESTAURANTS"

    # The original order is untouched.
    cart = (await c.get("/api/cart")).json()["cart"]
    assert [l["item_id"] for l in cart["lines"]] == ["r1-m1"]


async def test_clearing_releases_the_kitchen(client):
    c = await register_and_login(client, "kitchen3@dinemate.example")
    await c.post("/api/cart/lines", json={"item_id": "r1-m1", "quantity": 1})
    await c.delete("/api/cart")

    r = await c.post("/api/cart/lines", json={"item_id": "r5-m1", "quantity": 1})
    assert r.status_code == 200
    assert r.json()["cart"]["restaurant_id"] == "r5"


async def test_removing_last_line_releases_the_kitchen(client):
    c = await register_and_login(client, "kitchen4@dinemate.example")
    r = await c.post("/api/cart/lines", json={"item_id": "r1-m1", "quantity": 1})
    line_id = r.json()["cart"]["lines"][0]["line_id"]
    await c.patch(f"/api/cart/lines/{line_id}", json={"quantity": 0})

    r = await c.post("/api/cart/lines", json={"item_id": "r3-m1", "quantity": 1})
    assert r.status_code == 200
    assert r.json()["cart"]["restaurant_id"] == "r3"


async def test_order_snapshots_the_restaurant(client):
    c = await register_and_login(client, "kitchen5@dinemate.example")
    await c.post("/api/cart/lines", json={"item_id": "r3-m1", "quantity": 2})
    token = (await c.get("/api/cart")).json()["confirmation_token"]
    r = await c.post(
        "/api/orders",
        json={"confirmation_token": token},
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
