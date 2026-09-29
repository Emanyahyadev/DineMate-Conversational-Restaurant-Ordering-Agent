"""The conversation sidebar: what it lists, what it calls things, and delete.

These exercise the routes the sidebar actually calls, in the order it calls
them, because the reported failure ("threads do not save, delete does nothing")
is about the sequence, not about any single endpoint in isolation.
"""

from tests.conftest import register_and_login
from tests.integration.test_chat import stream


async def test_a_thread_appears_in_the_list_once_it_has_a_message(client):
    c = await register_and_login(client, "conv1@dinemate.example")

    events = await stream(c, "what do you have on the menu?")
    conv = [d for n, d in events if n == "start"][0]["conversation_id"]

    items = (await c.get("/api/conversations")).json()["items"]
    assert [i["id"] for i in items] == [conv]
    assert items[0]["empty"] is False


async def test_the_title_is_the_customers_own_words(client):
    c = await register_and_login(client, "conv2@dinemate.example")
    await stream(c, "do you have anything without chilli?")

    items = (await c.get("/api/conversations")).json()["items"]
    assert items[0]["title"] == "do you have anything without chilli?"


async def test_the_newest_thread_is_listed_first(client):
    c = await register_and_login(client, "conv3@dinemate.example")

    await stream(c, "show me the menu")
    older = (await c.get("/api/conversations")).json()["items"][0]["id"]

    blank = (await c.post("/api/conversations")).json()["id"]  # "New chat"
    newer_events = await stream(c, "actually, something with chicken", blank)
    newer = [d for n, d in newer_events if n == "start"][0]["conversation_id"]

    assert older != newer
    items = (await c.get("/api/conversations")).json()["items"]
    assert [i["id"] for i in items] == [newer, older], "most recently used first"

    # Returning to the older thread brings it back to the top.
    await stream(c, "on second thoughts", older)
    items = (await c.get("/api/conversations")).json()["items"]
    assert [i["id"] for i in items] == [older, newer]


async def test_new_chat_reuses_a_blank_thread_instead_of_stacking_them(client):
    c = await register_and_login(client, "conv7@dinemate.example")

    first = (await c.post("/api/conversations")).json()["id"]
    second = (await c.post("/api/conversations")).json()["id"]
    assert first == second, "pressing New chat twice should not make two threads"

    # And a blank thread is never listed, so it cannot crowd out real ones.
    assert (await c.get("/api/conversations")).json()["items"] == []


async def test_delete_removes_the_thread_and_its_messages(client):
    c = await register_and_login(client, "conv4@dinemate.example")
    events = await stream(c, "what do you have on the menu?")
    conv = [d for n, d in events if n == "start"][0]["conversation_id"]

    r = await c.delete(f"/api/conversations/{conv}")
    assert r.status_code == 204, r.text

    assert (await c.get("/api/conversations")).json()["items"] == []
    assert (await c.get(f"/api/conversations/{conv}")).status_code == 404


async def test_deleting_someone_elses_thread_is_a_404(client, other_client):
    owner = await register_and_login(client, "conv5@dinemate.example")
    events = await stream(owner, "show me the menu")
    conv = [d for n, d in events if n == "start"][0]["conversation_id"]

    intruder = await register_and_login(other_client, "conv6@dinemate.example")
    r = await intruder.delete(f"/api/conversations/{conv}")
    assert r.status_code == 404

    # ...and it is still there for the person it belongs to.
    assert (await owner.get(f"/api/conversations/{conv}")).status_code == 200
