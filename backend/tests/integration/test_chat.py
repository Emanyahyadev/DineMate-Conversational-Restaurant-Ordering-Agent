"""Agent turns over SSE, with the deterministic fake model."""
import json

from tests.conftest import register_and_login


async def stream(c, message, conversation_id=None):
    """Collect SSE events from a chat turn."""
    body = {"message": message}
    if conversation_id:
        body["conversation_id"] = conversation_id
    events = []
    async with c.stream("POST", "/api/chat", json=body) as r:
        assert r.status_code == 200, await r.aread()
        name = None
        async for line in r.aiter_lines():
            if line.startswith("event:"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("data:") and name:
                events.append((name, json.loads(line.split(":", 1)[1].strip())))
    return events


def reply_text(events):
    return "".join(d["delta"] for n, d in events if n == "token")


def tools_called(events):
    done = [d for n, d in events if n == "done"]
    return done[0]["tool_calls"] if done else []


async def test_menu_question_calls_search(client):
    c = await register_and_login(client, "chat1@dinemate.example")
    events = await stream(c, "what do you have on the menu?")
    assert "search_menu" in tools_called(events)
    assert reply_text(events)
    assert any(n == "done" for n, _ in events)


async def test_add_item_then_readback_then_confirm(client):
    c = await register_and_login(client, "chat2@dinemate.example")

    e1 = await stream(c, "I would like two margherita pizzas")
    conv = [d for n, d in e1 if n == "start"][0]["conversation_id"]
    assert "add_to_cart" in tools_called(e1)

    e2 = await stream(c, "that's everything", conv)
    assert "view_cart" in tools_called(e2)
    # BC-2: the read-back turn must NOT place the order
    assert "confirm_order" not in tools_called(e2)
    assert "$" in reply_text(e2)

    e3 = await stream(c, "yes, place it", conv)
    assert "confirm_order" in tools_called(e3)
    assert "ORD-" in reply_text(e3)

    r = await c.get("/api/orders")
    orders = r.json()["items"]
    assert len(orders) == 1
    assert orders[0]["lines"][0]["quantity"] == 2
    assert orders[0]["status"] == "confirmed"


async def test_confirm_without_readback_is_refused(client):
    """KPI A01 hard gate: consent cannot be skipped."""
    c = await register_and_login(client, "chat3@dinemate.example")
    e1 = await stream(c, "add a margherita")
    conv = [d for n, d in e1 if n == "start"][0]["conversation_id"]

    # Straight to 'yes' with no read-back in between.
    e2 = await stream(c, "yes, just order it now", conv)
    assert "confirm_order" in tools_called(e2)   # the model tried

    r = await c.get("/api/orders")
    assert r.json()["items"] == []               # ...and the system refused


async def test_chat_requires_auth(client):
    r = await client.post("/api/chat", json={"message": "hello"})
    assert r.status_code == 401


async def test_body_cannot_supply_user_id(client):
    c = await register_and_login(client, "chat4@dinemate.example")
    r = await c.post("/api/chat", json={"message": "hi", "user_id": "someone-else"})
    assert r.status_code == 400  # extra="forbid"
