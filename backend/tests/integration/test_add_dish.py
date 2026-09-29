"""A restaurant putting a dish on its own menu.

The interesting cases are all about the boundary: whose menu it lands on, what
a price is allowed to be, and what the agent starts offering afterwards.
"""

from tests.conftest import register_and_login
from tests.security.test_kitchen_tenancy import make_staff

DISH = {"name": "Peshawari Karahi", "category": "Karahi & Curries", "price": "1850"}


async def test_a_dish_is_added_to_the_signed_in_restaurant(client):
    chef = await make_staff("add1@dinemate.example", "r4", client)

    r = await chef.post("/api/kitchen/menu", json=DISH)
    assert r.status_code == 201, r.text
    item = r.json()["item"]
    assert item["name"] == "Peshawari Karahi"
    assert item["price_cents"] == 1850
    assert item["is_available"] is True
    assert item["id"].startswith("r4-")

    board = (await chef.get("/api/kitchen/menu")).json()["items"]
    assert "Peshawari Karahi" in [i["name"] for i in board]


async def test_it_lands_on_no_other_restaurants_menu(client, other_client):
    chef4 = await make_staff("add2@dinemate.example", "r4", client)
    await chef4.post("/api/kitchen/menu", json=DISH)

    chef5 = await make_staff("add3@dinemate.example", "r5", other_client)
    board = (await chef5.get("/api/kitchen/menu")).json()["items"]
    assert "Peshawari Karahi" not in [i["name"] for i in board]


async def test_a_customer_cannot_add_a_dish(client):
    diner = await register_and_login(client, "notchef@dinemate.example")
    r = await diner.post("/api/kitchen/menu", json=DISH)
    assert r.status_code == 404


async def test_prices_are_read_the_way_people_type_them(client):
    chef = await make_staff("add4@dinemate.example", "r4", client)
    for typed, expected in [("1850", 1850), ("1,850", 1850), ("Rs 1850", 1850)]:
        r = await chef.post(
            "/api/kitchen/menu", json={**DISH, "name": f"Dish {typed}", "price": typed}
        )
        assert r.status_code == 201, r.text
        assert r.json()["item"]["price_cents"] == expected


async def test_a_price_of_zero_or_nonsense_is_refused(client):
    chef = await make_staff("add5@dinemate.example", "r4", client)
    for bad in ("0", "-50", "free", ""):
        r = await chef.post("/api/kitchen/menu", json={**DISH, "price": bad})
        assert r.status_code in (400, 422), f"{bad!r} was accepted"


async def test_an_invented_category_is_refused(client):
    """The category has a CHECK constraint; the message should arrive before it."""
    chef = await make_staff("add6@dinemate.example", "r4", client)
    r = await chef.post("/api/kitchen/menu", json={**DISH, "category": "Pizza"})
    assert r.status_code == 400
    assert "Karahi & Curries" in r.json()["error"]["message"]


async def test_the_same_dish_cannot_be_added_twice(client):
    chef = await make_staff("add7@dinemate.example", "r4", client)
    assert (await chef.post("/api/kitchen/menu", json=DISH)).status_code == 201
    again = await chef.post("/api/kitchen/menu", json={**DISH, "name": "peshawari karahi"})
    assert again.status_code == 409


async def test_a_new_dish_is_offered_to_customers_immediately(client):
    """The menu cache has to be invalidated, or the agent keeps the old list."""
    chef = await make_staff("add8@dinemate.example", "r4", client)
    await chef.post("/api/kitchen/menu", json={**DISH, "name": "Namak Mandi Special"})

    public = (await client.get("/api/menu?q=Namak Mandi Special")).json()["items"]
    assert "Namak Mandi Special" in [i["name"] for i in public]


async def test_a_new_dish_makes_no_allergen_promise(client):
    """Nobody has checked it yet, and Rule M3 will not let us imply otherwise."""
    from app.db.postgres import SessionLocal
    from app.services import menu_service

    chef = await make_staff("add9@dinemate.example", "r4", client)
    created = (
        await chef.post("/api/kitchen/menu", json={**DISH, "name": "Unchecked Dish"})
    ).json()["item"]

    async with SessionLocal() as s:
        stored = await menu_service.get_item(s, created["id"])
    assert stored["allergens_verified"] is False
    assert stored["allergens"] == []


async def test_the_form_is_told_which_categories_exist(client):
    chef = await make_staff("add10@dinemate.example", "r4", client)
    body = (await chef.get("/api/kitchen/menu/categories")).json()
    assert "Karahi & Curries" in body["items"]
    assert "Pizza" not in body["items"]
