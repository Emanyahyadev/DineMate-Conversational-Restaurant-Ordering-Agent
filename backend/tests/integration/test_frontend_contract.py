"""The exact call sequence the browser makes (FRONTEND_SPEC section 4)."""
import json

from app.config import settings
from tests.conftest import register_and_login


async def test_browser_order_path(client):
    """Cart -> read-back token -> ConfirmDialog -> POST /api/orders."""
    c = await register_and_login(client, "browser@dinemate.example")

    # MenuPanel
    menu = (await c.get("/api/menu")).json()
    assert menu["categories"]
    assert all("price_display" in i for i in menu["items"])

    # CartPanel adds
    r = await c.post("/api/cart/lines", json={"item_id": "r1-m1", "quantity": 1})
    assert r.status_code == 200

    # Quantity stepper SETS, never increments
    line_id = r.json()["cart"]["lines"][0]["line_id"]
    r = await c.patch(f"/api/cart/lines/{line_id}", json={"quantity": 2})
    assert r.json()["cart"]["lines"][0]["quantity"] == 2

    # GET /api/cart hands the UI its confirmation token
    r = await c.get("/api/cart")
    token = r.json()["confirmation_token"]
    assert token, "the Place order button needs a token"

    # ConfirmDialog -> POST /api/orders with an Idempotency-Key
    r = await c.post(
        "/api/orders",
        json={"confirmation_token": token, "fulfilment": "pickup", "notes": ""},
        headers={"Idempotency-Key": "browser-1"},
    )
    assert r.status_code == 201
    order = r.json()["order"]
    assert order["total_display"].startswith(settings.currency_symbol.strip())
    assert order["eta_minutes"] > 0

    # Cart is empty afterwards, so the panel and the total bar disappear
    assert (await c.get("/api/cart")).json()["cart"]["lines"] == []


async def test_cart_change_disables_place_button(client):
    """US-15: a mutation must invalidate the token the UI is holding."""
    c = await register_and_login(client, "stale-ui@dinemate.example")
    await c.post("/api/cart/lines", json={"item_id": "r1-m1", "quantity": 1})
    token = (await c.get("/api/cart")).json()["confirmation_token"]

    await c.post("/api/cart/lines", json={"item_id": "r1-m5", "quantity": 1})

    r = await c.post(
        "/api/orders",
        json={"confirmation_token": token},
        headers={"Idempotency-Key": "stale-ui"},
    )
    assert r.status_code == 409


async def test_sse_frames_match_the_documented_contract(client):
    """Every event the client switches on, in the documented shape."""
    c = await register_and_login(client, "sse@dinemate.example")
    seen: dict[str, dict] = {}
    async with c.stream("POST", "/api/chat", json={"message": "show me the menu"}) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        name = None
        async for line in r.aiter_lines():
            if line.startswith("event:"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("data:") and name:
                seen.setdefault(name, json.loads(line.split(":", 1)[1].strip()))

    assert "start" in seen and "conversation_id" in seen["start"]
    assert "token" in seen and "delta" in seen["token"]
    assert "done" in seen and "duration_ms" in seen["done"]
    assert "tool" in seen
    assert {"name", "phase", "label"} <= set(seen["tool"])


async def test_profile_and_memories_shapes(client):
    c = await register_and_login(client, "prof@dinemate.example")
    r = await c.get("/api/profile")
    assert set(r.json()) == {"user", "stats"}
    assert "orders_placed" in r.json()["stats"]

    r = await c.get("/api/profile/memories")
    assert set(r.json()) == {"preferences", "facts"}
