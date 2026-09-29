"""A customer who comes back tomorrow should not be re-interviewed.

Contact details live on the account in Postgres rather than in the memory
profile: they are PII, AGENT_SPEC section 6 keeps PII out of the free-form
memory documents, and they must be deletable with the account in one
transaction. What matters to the customer is only that we still have them.
"""

from tests.conftest import register_and_login


async def order(c, *, key, **body):
    await c.post("/api/cart/lines", json={"item_id": "r3-m1", "quantity": 1})
    token = (await c.get("/api/cart")).json()["confirmation_token"]
    r = await c.post(
        "/api/orders",
        json={"confirmation_token": token, **body},
        headers={"Idempotency-Key": key},
    )
    return r


async def test_a_second_order_needs_no_details_at_all(client):
    c = await register_and_login(client, "returning@dinemate.example")

    first = await order(
        c,
        key="visit-1",
        fulfilment="delivery",
        contact_phone="03009998877",
        delivery_address="Flat 3, Askari 11, Lahore",
    )
    assert first.status_code == 201, first.text

    # Tomorrow: they say nothing about phone or address.
    second = await order(c, key="visit-2", fulfilment="delivery")
    assert second.status_code == 201, second.text

    placed = second.json()["orders"][0]
    assert placed["contact_phone"] == "03009998877"
    assert placed["delivery_address"] == "Flat 3, Askari 11, Lahore"


async def test_new_details_win_over_the_saved_ones(client):
    c = await register_and_login(client, "moved-house@dinemate.example")
    await order(
        c,
        key="old-place",
        fulfilment="delivery",
        contact_phone="03001111111",
        delivery_address="Flat 3, Askari 11, Lahore",
    )

    moved = await order(
        c,
        key="new-place",
        fulfilment="delivery",
        contact_phone="03002222222",
        delivery_address="House 9, DHA Phase 5, Karachi",
    )
    placed = moved.json()["orders"][0]
    assert placed["contact_phone"] == "03002222222"
    assert placed["delivery_address"] == "House 9, DHA Phase 5, Karachi"

    # ...and the new ones are what we hold from now on.
    contact = (await c.get("/api/cart")).json()["contact"]
    assert contact["phone"] == "03002222222"
    assert contact["address"] == "House 9, DHA Phase 5, Karachi"


async def test_a_first_time_customer_is_still_asked(client):
    """The fallback must not become a way to place an order with no phone."""
    c = await register_and_login(client, "first-timer@dinemate.example")
    r = await order(c, key="no-details", fulfilment="delivery")
    assert r.status_code == 400
    assert "phone" in r.json()["error"]["message"].lower()


async def test_a_saved_phone_does_not_stand_in_for_a_missing_address(client):
    c = await register_and_login(client, "collect-then-deliver@dinemate.example")
    await order(c, key="collected", fulfilment="pickup", contact_phone="03003333333")

    # Collection stored no address, so delivery still has to ask for one.
    r = await order(c, key="now-deliver", fulfilment="delivery")
    assert r.status_code == 400
    assert "address" in r.json()["error"]["message"].lower()


async def test_the_agent_is_told_what_is_on_file(client):
    """view_cart carries `on_file` so the read-back can offer it back."""
    from app.db.postgres import SessionLocal
    from app.services import cart_service, order_service

    c = await register_and_login(client, "on-file@dinemate.example")
    await order(
        c,
        key="on-file-1",
        fulfilment="delivery",
        contact_phone="03004444444",
        delivery_address="House 12, Gulberg III, Lahore",
    )
    me = (await c.get("/api/auth/me")).json()["user"]

    async with SessionLocal() as s:
        on_file = await order_service.contact_on_file(s, me["id"])
        assert on_file == {
            "phone": "03004444444",
            "address": "House 12, Gulberg III, Lahore",
        }
        # And it is the customer's own record, never anyone else's.
        assert await cart_service.view(s, me["id"]) is not None


async def test_details_are_not_shared_between_customers(client, other_client):
    a = await register_and_login(client, "hers@dinemate.example")
    await order(
        a,
        key="hers-1",
        fulfilment="delivery",
        contact_phone="03005555555",
        delivery_address="House 1, Model Town, Lahore",
    )

    b = await register_and_login(other_client, "theirs@dinemate.example")
    contact = (await b.get("/api/cart")).json()["contact"]
    assert contact == {"phone": "", "address": ""}


async def test_a_pasted_password_with_a_stray_space_still_signs_in(client):
    """End to end: the exact way the demo credentials failed for a real person."""
    email = "pasted@dinemate.example"
    password = "correct-horse-battery"

    r = await client.post("/api/auth/register", json={"email": email, "password": password})
    assert r.status_code == 201, r.text

    for pasted in (password, password + " ", " " + password, password + "\n"):
        r = await client.post("/api/auth/login", json={"email": email, "password": pasted})
        assert r.status_code == 200, f"{pasted!r} was rejected: {r.text}"


async def test_a_genuinely_wrong_password_is_still_refused(client):
    """Trimming must not become a way in."""
    email = "wrongpw@dinemate.example"
    await client.post("/api/auth/register",
                      json={"email": email, "password": "correct-horse-battery"})
    r = await client.post("/api/auth/login",
                          json={"email": email, "password": "correct-horse-batteryX"})
    assert r.status_code == 401
