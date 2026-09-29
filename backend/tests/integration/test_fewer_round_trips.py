"""The responses the UI stopped re-reading the server for.

Both screens used to answer a click by refetching everything: the browse menu
paged one request per restaurant, and the dashboard reloaded four endpoints
after every button press. They now render from what the mutation itself
returned, which is only safe while these responses stay complete - so that is
what is checked here rather than any timing.
"""

from tests.conftest import register_and_login
from tests.security.test_kitchen_tenancy import make_staff, place_order


async def test_the_whole_menu_arrives_in_one_request(client):
    """MenuPanel reads /api/menu/full once instead of paging by restaurant."""
    board = (await client.get("/api/menu/full")).json()

    assert board["categories"], "the courses come with the board"
    assert board["restaurants"], "so do the kitchens, with their ratings"
    assert all("rating" in r for r in board["restaurants"])

    # /api/menu caps itself for the agent's prompt budget. This must not: a
    # browse that silently drops dishes is worse than a slow one.
    capped = (await client.get("/api/menu")).json()["items"]
    assert len(board["items"]) > len(capped)

    # Every kitchen is represented, which is what paging by restaurant bought.
    served = {i["restaurant_id"] for i in board["items"]}
    assert served >= {r["id"] for r in board["restaurants"] if r["item_count"]}

    # And each dish is renderable as-is: the panel never computes money.
    assert all(i["price_display"] and i["name"] for i in board["items"])


async def test_advancing_a_ticket_answers_with_a_whole_ticket(client, other_client):
    """The board swaps one row for this response instead of re-reading the pass."""
    customer = await register_and_login(client, "one-trip@dinemate.example")
    order = await place_order(customer, "r3-m1")
    chef = await make_staff("chef-one-trip@dinemate.example", "r3", other_client)

    r = await chef.post(
        f"/api/kitchen/orders/{order['id']}/advance", json={"to_status": "preparing"}
    )
    assert r.status_code == 200, r.text
    moved = r.json()["order"]

    # The three fields a queue entry carries beyond a plain order. Without them
    # the replaced row loses its timer and its next button.
    assert moved["status"] == "preparing"
    assert moved["waiting_minutes"] >= 0
    assert moved["is_late"] is False
    assert "ready" in moved["next_statuses"]

    # Same shape as the row it replaces.
    live = (await chef.get("/api/kitchen/orders")).json()["items"]
    listed = next(o for o in live if o["id"] == order["id"])
    assert set(moved) >= set(listed)


async def test_the_ratings_panel_still_gets_its_spread(client, other_client):
    """Average, count and distribution now come from one query, not three."""
    chef = await make_staff("chef-scores@dinemate.example", "r3", other_client)

    body = (await chef.get("/api/kitchen/ratings")).json()
    assert set(body) == {"summary", "distribution", "recent"}
    assert set(body["summary"]) == {"average", "count"}
    # Five bars, always, so an unrated kitchen draws an empty spread rather
    # than nothing at all.
    assert sorted(int(k) for k in body["distribution"]) == [1, 2, 3, 4, 5]

    # Nobody has rated this kitchen: unknown, not zero.
    assert body["summary"]["count"] == 0
    assert body["summary"]["average"] is None
