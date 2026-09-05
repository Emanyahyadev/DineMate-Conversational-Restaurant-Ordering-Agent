"""Agent tools: menu lookup, order placement, order status."""

from __future__ import annotations

import random
from datetime import datetime, timezone

from agents import RunContextWrapper, function_tool
from pydantic import BaseModel

from app.agent.menu import MENU, MENU_BY_ID, MENU_BY_NAME
from app.db.mongo import db

orders = db["orders"]

STATUS_FLOW = ["received", "preparing", "ready", "out_for_delivery", "delivered"]


class ChatContext(BaseModel):
    """Trusted per-request context; never supplied by the model."""

    user_id: str


class OrderLine(BaseModel):
    item: str  # menu item id or name
    quantity: int = 1


def _resolve(item: str) -> dict | None:
    return MENU_BY_ID.get(item) or MENU_BY_NAME.get(item.strip().lower())


@function_tool
async def get_menu(category: str | None = None, tag: str | None = None) -> list[dict]:
    """Return the restaurant menu, optionally filtered.

    Args:
        category: Restrict to one category, e.g. "Pizza", "Pasta", "Dessert".
        tag: Restrict to a dietary tag, e.g. "vegan", "vegetarian", "spicy".
    """
    items = MENU
    if category:
        items = [i for i in items if i["category"].lower() == category.strip().lower()]
    if tag:
        items = [i for i in items if tag.strip().lower() in i["tags"]]
    return items


@function_tool
async def place_order(
    ctx: RunContextWrapper[ChatContext], lines: list[OrderLine], notes: str = ""
) -> dict:
    """Place an order for the customer and return the order id and total.

    Args:
        lines: Items and quantities to order.
        notes: Any special instructions from the customer.
    """
    resolved: list[dict] = []
    unknown: list[str] = []
    for line in lines:
        item = _resolve(line.item)
        if item is None:
            unknown.append(line.item)
            continue
        resolved.append(
            {
                "id": item["id"],
                "name": item["name"],
                "quantity": max(1, line.quantity),
                "unit_price": item["price"],
            }
        )

    if unknown:
        return {"error": f"Not on the menu: {', '.join(unknown)}"}
    if not resolved:
        return {"error": "No items to order."}

    total = round(sum(line["unit_price"] * line["quantity"] for line in resolved), 2)
    order = {
        "_id": f"ORD-{random.randint(100000, 999999)}",
        "user_id": ctx.context.user_id,
        "items": resolved,
        "notes": notes,
        "total": total,
        "status": STATUS_FLOW[0],
        "created_at": datetime.now(timezone.utc),
    }
    await orders.insert_one(order)
    return {"order_id": order["_id"], "total": total, "status": order["status"], "items": resolved}


@function_tool
async def order_status(ctx: RunContextWrapper[ChatContext], order_id: str) -> dict:
    """Look up the current status of one of this customer's orders.

    Args:
        order_id: The order id returned when the order was placed, e.g. "ORD-123456".
    """
    order = await orders.find_one(
        {"_id": order_id.strip().upper(), "user_id": ctx.context.user_id}
    )
    if not order:
        return {"error": f"No order found with id {order_id}."}
    return {
        "order_id": order["_id"],
        "status": order["status"],
        "total": order["total"],
        "items": order["items"],
        "placed_at": order["created_at"].isoformat(),
    }


TOOLS = [get_menu, place_order, order_status]
