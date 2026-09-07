"""Long-term memory has to survive the turn, and cross conversations.

The bug this guards: the memory write sat after the generator's final yield, so
a client that stopped reading at `done` - which is every sensible client -
abandoned the generator and the memory was never written. It looked like the
agent simply forgot.
"""
import json

from tests.conftest import register_and_login


async def stream_turn(c, message, conversation_id=None, stop_at_done=True):
    body = {"message": message}
    if conversation_id:
        body["conversation_id"] = conversation_id
    events = []
    async with c.stream("POST", "/api/chat", json=body) as r:
        assert r.status_code == 200
        name = None
        async for line in r.aiter_lines():
            if line.startswith("event:"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("data:") and name:
                events.append((name, json.loads(line.split(":", 1)[1].strip())))
                # Stop the moment the turn is done, exactly as a real client does.
                if stop_at_done and name in ("done", "error"):
                    break
    return events


async def test_memory_is_written_even_when_the_client_stops_at_done(client):
    c = await register_and_login(client, "mem-persist@dinemate.example")
    events = await stream_turn(c, "My name is Bilal and I am allergic to peanuts.")

    done = [d for n, d in events if n == "done"]
    assert done, "no done event"
    assert done[0]["memories_written"] >= 2, done[0]

    stored = (await c.get("/api/profile/memories")).json()
    texts = {f["text"] for f in stored["facts"]}
    assert "Allergic to peanuts" in texts
    assert "Prefers to be called Bilal" in texts


async def test_memory_survives_into_a_brand_new_conversation(client):
    c = await register_and_login(client, "mem-cross@dinemate.example")
    await stream_turn(c, "I am vegetarian and allergic to peanuts.")

    # A new thread is a new transcript, never a new customer (Rule V4).
    fresh = await c.post("/api/conversations")
    assert fresh.status_code == 201

    greeting = (await c.get("/api/greeting")).json()
    assert greeting["name"] is None or isinstance(greeting["name"], str)
    assert "peanut" in " ".join(greeting["known_allergens"])
    assert "Vegetarian" in greeting["known_preferences"]
    assert greeting["returning"] is True


async def test_a_recorded_allergy_filters_the_menu_the_agent_sees(client):
    """Rule N3: the allergen filter is applied server-side, so the model
    forgetting to pass it cannot produce an unsafe suggestion."""
    from app.db.postgres import SessionLocal
    from app.services import memory_service, menu_service

    c = await register_and_login(client, "mem-allergy@dinemate.example")
    await stream_turn(c, "I am allergic to peanuts.")

    # Salan is the one dish on this menu built on a peanut gravy.
    salan = (await c.get("/api/menu/r3-m8")).json()
    assert "peanut" in salan["allergens"]

    me = (await c.get("/api/auth/me")).json()["user"]
    banned = await memory_service.known_allergens(me["id"])
    assert banned == ["peanut"], banned

    async with SessionLocal() as session:
        filtered = await menu_service.search(
            session, query="salan", exclude_allergens=banned, limit=10
        )
        # Same search with nothing on file, so this proves the filter rather
        # than a spelling mistake.
        baseline = await menu_service.search(session, query="salan", limit=10)

    assert "Salan" not in [i["name"] for i in filtered]
    assert "Salan" in [i["name"] for i in baseline]


async def test_someone_with_no_allergies_gets_the_whole_menu(client):
    from app.services import memory_service

    c = await register_and_login(client, "mem-noallergy@dinemate.example")
    me = (await c.get("/api/auth/me")).json()["user"]
    assert await memory_service.known_allergens(me["id"]) == []


async def test_deleting_a_memory_removes_it_from_the_greeting(client):
    """US-24: the customer can make DineMate forget."""
    c = await register_and_login(client, "mem-forget@dinemate.example")
    await stream_turn(c, "I am allergic to peanuts.")

    stored = (await c.get("/api/profile/memories")).json()
    peanut = next(f for f in stored["facts"] if "peanut" in f["text"].lower())
    assert (await c.delete(f"/api/profile/memories/{peanut['id']}")).status_code == 204

    greeting = (await c.get("/api/greeting")).json()
    assert greeting["known_allergens"] == []
