"""Ratings, and who is entitled to leave one.

A score is only worth showing if it came from someone who actually ate. That is
the point of anchoring a rating to a completed order rather than to a
restaurant, and most of what follows is about holding that line.
"""

from tests.conftest import register_and_login
from tests.security.test_kitchen_tenancy import make_staff, place_order


async def complete(chef, order_id):
    """Walk a pickup order to completed, the way the kitchen would."""
    for step in ("preparing", "ready", "completed"):
        r = await chef.post(f"/api/kitchen/orders/{order_id}/advance", json={"to_status": step})
        assert r.status_code == 200, r.text


async def test_a_completed_order_can_be_rated(client, other_client):
    diner = await register_and_login(client, "rate1@dinemate.example")
    order = await place_order(diner, "r3-m1")
    chef = await make_staff("chef-rate1@dinemate.example", "r3", other_client)
    await complete(chef, order["id"])

    r = await diner.post(
        f"/api/orders/{order['id']}/rating", json={"stars": 5, "comment": "Excellent biryani"}
    )
    assert r.status_code == 201, r.text
    assert r.json()["rating"]["stars"] == 5


async def test_an_order_still_cooking_cannot_be_rated(client):
    diner = await register_and_login(client, "rate2@dinemate.example")
    order = await place_order(diner, "r3-m1")

    r = await diner.post(f"/api/orders/{order['id']}/rating", json={"stars": 5})
    assert r.status_code == 400
    assert "completed" in r.json()["error"]["message"].lower()


async def test_the_same_order_cannot_be_rated_twice(client, other_client):
    diner = await register_and_login(client, "rate3@dinemate.example")
    order = await place_order(diner, "r3-m1")
    chef = await make_staff("chef-rate3@dinemate.example", "r3", other_client)
    await complete(chef, order["id"])

    assert (await diner.post(f"/api/orders/{order['id']}/rating", json={"stars": 4})).status_code == 201
    again = await diner.post(f"/api/orders/{order['id']}/rating", json={"stars": 1})
    assert again.status_code == 409


async def test_you_cannot_rate_somebody_elses_order(client, other_client):
    owner = await register_and_login(client, "rate4@dinemate.example")
    order = await place_order(owner, "r3-m1")

    intruder = await register_and_login(other_client, "rate5@dinemate.example")
    r = await intruder.post(f"/api/orders/{order['id']}/rating", json={"stars": 1})
    # NOT_FOUND, never FORBIDDEN: a 403 would confirm the order exists.
    assert r.status_code == 404


async def test_stars_outside_one_to_five_are_refused(client):
    diner = await register_and_login(client, "rate6@dinemate.example")
    order = await place_order(diner, "r3-m1")
    for bad in (0, 6, -1, 99):
        r = await diner.post(f"/api/orders/{order['id']}/rating", json={"stars": bad})
        assert r.status_code in (400, 422), f"{bad} was accepted"


async def test_the_restaurant_sees_its_own_score(client, other_client):
    diner = await register_and_login(client, "rate7@dinemate.example")
    order = await place_order(diner, "r3-m1")
    chef = await make_staff("chef-rate7@dinemate.example", "r3", other_client)
    await complete(chef, order["id"])
    await diner.post(f"/api/orders/{order['id']}/rating", json={"stars": 4, "comment": "Good"})

    board = (await chef.get("/api/kitchen/ratings")).json()
    assert board["summary"] == {"average": 4.0, "count": 1}
    assert board["distribution"]["4"] == 1
    assert board["recent"][0]["comment"] == "Good"


async def test_a_restaurant_never_sees_another_kitchens_ratings(client, other_client):
    diner = await register_and_login(client, "rate8@dinemate.example")
    order = await place_order(diner, "r3-m1")
    chef3 = await make_staff("chef-r3@dinemate.example", "r3", other_client)
    await complete(chef3, order["id"])
    await diner.post(f"/api/orders/{order['id']}/rating", json={"stars": 5})

    chef5 = await make_staff("chef-r5@dinemate.example", "r5", other_client)
    board = (await chef5.get("/api/kitchen/ratings")).json()
    assert board["summary"]["count"] == 0


async def test_a_customer_cannot_read_the_ratings_board(client):
    diner = await register_and_login(client, "rate9@dinemate.example")
    assert (await diner.get("/api/kitchen/ratings")).status_code == 404


async def test_the_restaurant_list_carries_the_score(client, other_client):
    diner = await register_and_login(client, "rate10@dinemate.example")
    order = await place_order(diner, "r3-m1")
    chef = await make_staff("chef-rate10@dinemate.example", "r3", other_client)
    await complete(chef, order["id"])
    await diner.post(f"/api/orders/{order['id']}/rating", json={"stars": 5})

    items = (await client.get("/api/restaurants")).json()["items"]
    rated = next(i for i in items if i["id"] == "r3")
    assert rated["rating"] == {"average": 5.0, "count": 1}

    # An unrated kitchen has no score, not a zero.
    unrated = next(i for i in items if i["id"] == "r2")
    assert unrated["rating"] == {"average": None, "count": 0}


async def test_the_order_list_says_what_can_be_rated(client, other_client):
    diner = await register_and_login(client, "rate11@dinemate.example")
    order = await place_order(diner, "r3-m1")

    mine = (await diner.get("/api/orders")).json()["items"][0]
    assert mine["can_rate"] is False and mine["rating"] is None

    chef = await make_staff("chef-rate11@dinemate.example", "r3", other_client)
    await complete(chef, order["id"])
    mine = (await diner.get("/api/orders")).json()["items"][0]
    assert mine["can_rate"] is True

    await diner.post(f"/api/orders/{order['id']}/rating", json={"stars": 3})
    mine = (await diner.get("/api/orders")).json()["items"][0]
    assert mine["can_rate"] is False
    assert mine["rating"]["stars"] == 3
