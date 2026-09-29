"""What the chef marks is what the customer sees.

The kitchen dashboard and the customer's order view are two windows onto one
row, so this walks a real ticket down the state machine from the kitchen side
and checks the customer side after every step - including what the agent says
when asked, since that is how most customers will actually ask.
"""

import pytest

from tests.conftest import register_and_login
from tests.integration.test_chat import reply_text, stream
from tests.security.test_kitchen_tenancy import make_staff, place_order


async def test_the_customer_sees_each_step_the_chef_marks(client, other_client):
    customer = await register_and_login(client, "diner-status@dinemate.example")
    order = await place_order(customer, "r3-m1")
    chef = await make_staff("chef-status@dinemate.example", "r3", other_client)

    assert order["status"] == "confirmed"

    for step in ("preparing", "ready", "completed"):
        r = await chef.post(
            f"/api/kitchen/orders/{order['id']}/advance", json={"to_status": step}
        )
        assert r.status_code == 200, r.text
        assert r.json()["order"]["status"] == step

        mine = (await customer.get("/api/orders")).json()["items"]
        assert [o["status"] for o in mine if o["id"] == order["id"]] == [step], (
            f"customer still sees the old status after the chef marked {step}"
        )


async def test_the_ticket_carries_the_chefs_history(client, other_client):
    customer = await register_and_login(client, "diner-events@dinemate.example")
    order = await place_order(customer, "r3-m1")
    chef = await make_staff("chef-events@dinemate.example", "r3", other_client)

    await chef.post(
        f"/api/kitchen/orders/{order['id']}/advance",
        json={"to_status": "preparing", "reason": "on the pan"},
    )

    detail = (await customer.get(f"/api/orders/{order['id']}")).json()["order"]
    events = detail["events"]
    assert events[-1]["to_status"] == "preparing"
    assert events[-1]["actor"] == "staff", "the customer can see the kitchen acted"


async def test_asking_the_agent_reports_the_kitchens_status(client, other_client):
    customer = await register_and_login(client, "diner-asks@dinemate.example")
    order = await place_order(customer, "r3-m1")
    chef = await make_staff("chef-asks@dinemate.example", "r3", other_client)

    await chef.post(
        f"/api/kitchen/orders/{order['id']}/advance", json={"to_status": "preparing"}
    )

    events = await stream(customer, "where is my order?")
    assert "preparing" in reply_text(events).lower()


async def test_the_chef_cannot_skip_the_state_machine(client, other_client):
    """Rule L1 holds on the dashboard too, not only on the internal route."""
    customer = await register_and_login(client, "diner-skip@dinemate.example")
    order = await place_order(customer, "r3-m1")
    chef = await make_staff("chef-skip@dinemate.example", "r3", other_client)

    r = await chef.post(
        f"/api/kitchen/orders/{order['id']}/advance", json={"to_status": "completed"}
    )
    assert r.status_code == 409, r.text

    mine = (await customer.get("/api/orders")).json()["items"]
    assert mine[0]["status"] == "confirmed", "a refused move must not change anything"


@pytest.mark.parametrize("bad", ["not-a-status", "draft"])
async def test_an_unknown_status_is_refused(client, other_client, bad):
    customer = await register_and_login(client, f"diner-{bad}@dinemate.example")
    order = await place_order(customer, "r3-m1")
    chef = await make_staff(f"chef-{bad}@dinemate.example", "r3", other_client)

    r = await chef.post(
        f"/api/kitchen/orders/{order['id']}/advance", json={"to_status": bad}
    )
    assert r.status_code in (409, 422), r.text
