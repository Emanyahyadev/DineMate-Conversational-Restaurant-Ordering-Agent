"""A deterministic stand-in for DeepSeek.

Used by the test suite and by the eval harness in recorded mode, so accuracy
gates run for free and identically on every machine (EVAL_PLAN.md section 6).

It is a rule-based interpreter of the customer's last message, not a language
model. It exists to exercise the *system*: tool selection, the confirmation
protocol, cart arithmetic and error handling. The real model's judgement is
measured separately by the live eval run.
"""

from __future__ import annotations

import ast
import json
import re
from typing import Any

from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call
from agents.usage import Usage

NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


def _text_of(item: Any) -> str:
    if isinstance(item, dict):
        content = item.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return " ".join(
                c.get("text", "") for c in content if isinstance(c, dict)
            )
    return ""


def _role_of(item: Any) -> str:
    return item.get("role", "") if isinstance(item, dict) else ""


def _last_user_message(input_items: Any) -> str:
    if isinstance(input_items, str):
        return input_items
    for item in reversed(list(input_items or [])):
        if _role_of(item) == "user":
            return _text_of(item)
    return ""


def _tool_outputs(input_items: Any) -> list[dict[str, Any]]:
    """Tool results already in this run, newest last."""
    out: list[dict[str, Any]] = []
    for item in list(input_items or []):
        if not isinstance(item, dict):
            continue
        if item.get("type") == "function_call_output":
            raw = item.get("output")
            out.append({"call_id": item.get("call_id"), "data": _parse(raw)})
    return out


def _called_tools(input_items: Any) -> list[str]:
    names = []
    for item in list(input_items or []):
        if isinstance(item, dict) and item.get("type") == "function_call":
            names.append(item.get("name", ""))
    return names


def _parse(raw: Any) -> Any:
    """Tool outputs arrive as Python repr, not JSON, so try both."""
    if not isinstance(raw, str):
        return raw
    for loader in (json.loads, ast.literal_eval):
        try:
            return loader(raw)
        except (ValueError, SyntaxError, TypeError):
            continue
    return raw


def _quantity(text: str) -> int:
    m = re.search(r"\b(\d{1,2})\b", text)
    if m:
        return int(m.group(1))
    for word, n in NUMBER_WORDS.items():
        if re.search(rf"\b{word}\b", text):
            return n
    return 1


def _fmt_cart(cart: dict[str, Any]) -> str:
    if not cart.get("lines"):
        return "Your order is empty at the moment."
    parts = [
        f"{l['quantity']} x {l['name']} - {l['line_total_display']}" for l in cart["lines"]
    ]
    return (
        "Here is your order: "
        + "; ".join(parts)
        + f". Subtotal {cart['subtotal_display']}, tax {cart['tax_display']}, "
        f"total {cart['total_display']}. Shall I place it?"
    )


def _asked_for_specific_dish(text: str) -> bool:
    """True when the customer named something rather than browsing."""
    return bool(
        re.search(
            r"\b(add|i'?ll have|i want|i'?d like|i would like|i'?ll take|get me|"
            r"order me|can i get|give me)\b",
            text,
        )
    )


class _Responder:
    """Maps (last user message, tool results so far) to the next model step."""

    def __call__(self, call: Any) -> ModelStep:
        text = _last_user_message(call.input).lower()
        called = _called_tools(call.input)
        results = _tool_outputs(call.input)
        latest = results[-1]["data"] if results else None
        usage = Usage(requests=1, input_tokens=800, output_tokens=60, total_tokens=860)

        def say(msg: str) -> ModelStep:
            return ModelStep(output=[assistant_message(msg)], usage=usage)

        def call_tool(name: str, args: dict[str, Any]) -> ModelStep:
            if name in called:
                return say(
                    "Sorry - I could not complete that. Could you tell me again what "
                    "you would like?"
                )
            return ModelStep(
                output=[function_call(name, args, call_id=f"call_{name}_{len(called)}")],
                usage=usage,
            )

        # ---- react to the most recent tool result --------------------------
        if latest is not None and isinstance(latest, dict) and "error" in latest:
            err = latest["error"]
            return say(f"Sorry - {err.get('message', 'that did not work.')}")

        if called:
            last_tool = called[-1]

            if last_tool == "get_full_menu" and isinstance(latest, dict):
                kitchens = latest.get("kitchens", [])
                names = "; ".join(k["restaurant"] for k in kitchens)
                return say(
                    f"We have {latest.get('total_items', 0)} dishes across {names}. "
                    "Which kitchen would you like to look at?"
                )

            if last_tool == "search_menu":
                items = latest if isinstance(latest, list) else []
                if not items:
                    return say("I could not find anything matching that on the menu.")
                named = _guess_item(text)
                if named is None and _asked_for_specific_dish(text):
                    listed = "; ".join(i["name"] for i in items[:3])
                    return say(
                        "We do not have that, I am afraid. What we do have includes "
                        f"{listed}. Would any of those work?"
                    )
                listed = "; ".join(f"{i['name']} at {i['price_display']}" for i in items[:3])
                return say(f"Here is what I would suggest: {listed}. What would you like?")

            if last_tool == "get_item_details" and isinstance(latest, dict):
                return say(
                    f"{latest['name']} is {latest['price_display']}. {latest['description']} "
                    f"Allergens: {', '.join(latest['allergens']) or 'none listed'}."
                )

            if last_tool in ("add_to_cart", "update_cart_item", "remove_from_cart"):
                cart = latest if isinstance(latest, dict) else {}
                lines = cart.get("lines", [])
                if lines:
                    last = lines[-1]
                    return say(
                        f"Added. That is {last['quantity']} x {last['name']}. "
                        f"Your total so far is {cart.get('total_display', '')}. "
                        "Anything else?"
                    )
                return say("Done. Your order is empty now. Anything else?")

            if last_tool == "view_cart" and isinstance(latest, dict):
                lines = latest.get("lines", [])
                target = _match_line(text, lines)

                if re.search(r"\b(remove|drop|take off|delete|without|no more)\b", text):
                    if target:
                        return call_tool("remove_from_cart", {"line_id": target["line_id"]})
                    return say("Which item would you like me to take off?")

                if re.search(r"\b(make it|change it to|instead)\b", text):
                    if target or len(lines) == 1:
                        line = target or lines[0]
                        return call_tool(
                            "update_cart_item",
                            {"line_id": line["line_id"], "quantity": _quantity(text)},
                        )
                    return say("Which item should I change?")

                return say(_fmt_cart(latest))

            if last_tool == "confirm_order" and isinstance(latest, dict):
                return say(
                    f"All set. Your order is {latest['id']} and the total is "
                    f"{latest['total_display']}. It should be about "
                    f"{latest['eta_minutes']} minutes."
                )

            if last_tool == "order_status" and isinstance(latest, dict):
                return say(
                    f"Order {latest['id']} is {latest['status'].replace('_', ' ')}, "
                    f"total {latest['total_display']}."
                )

            if last_tool == "cancel_order" and isinstance(latest, dict):
                return say(f"Order {latest['id']} is cancelled.")

        # ---- decide the first action of the turn ----------------------------
        # Confirmation must follow a read-back, never precede one (BC-2).
        if re.search(r"\b(yes|yeah|yep|confirm|place it|go ahead|order it|do it)\b", text):
            return call_tool("confirm_order", {"fulfilment": "pickup"})

        if re.search(r"\bcancel\b", text):
            m = re.search(r"(ORD-\d{6})", text.upper())
            return call_tool("cancel_order", {"order_id": m.group(1) if m else ""})

        if re.search(r"\b(where.*order|order status|my food|how long)\b", text):
            m = re.search(r"(ORD-\d{6})", text.upper())
            return call_tool("order_status", {"order_id": m.group(1)} if m else {})

        if re.search(r"\b(that'?s (it|everything|all)|done|nothing else|check ?out|my total|"
                     r"what do i owe|review)\b", text):
            return call_tool("view_cart", {})

        if re.search(r"\b(remove|drop|take off|delete)\b", text):
            return call_tool("view_cart", {})

        if re.search(r"\b(make it|change it to|instead of)\b", text):
            return call_tool("view_cart", {})

        if re.search(r"\b(what'?s in|tell me about|describe|ingredients|allergen)\b", text):
            item = _guess_item(text)
            if item is None:
                return call_tool("search_menu", {"query": text[:60]})
            return call_tool("get_item_details", {"item_id": item})

        if re.search(r"\b(add|i'?ll have|i want|get me|order me|can i get|give me|"
                     r"i'?d like|i would like|i'?ll take|bring me|let'?s do)\b", text):
            item = _guess_item(text)
            if item is None:
                # Nothing on the menu matches: look it up rather than guess (BC-1).
                return call_tool("search_menu", {"query": text[:60]})
            return call_tool("add_to_cart", {"item_id": item, "quantity": _quantity(text)})

        # Asking for "the menu" wants all of it. This has to be tested before the
        # generic browse branch below, which would answer with a sample instead.
        if re.search(
            r"(what'?s on the menu|whats on the menu|full menu|entire menu|"
            r"see the menu|show me the menu|the whole menu)",
            text,
        ):
            return call_tool("get_full_menu", {})

        if re.search(r"\b(menu|what do you have|what'?s good|recommend|hungry|options|"
                     r"vegetarian|vegan|spicy|gluten|dessert|drink|biryani|karahi|naan)\b", text):
            args: dict[str, Any] = {"query": text[:60]}
            tags = [
                tag
                for tag in ("vegetarian", "vegan", "spicy", "gluten_free")
                if tag in text or tag.replace("_", " ") in text
            ]
            if tags:
                args["dietary_tags"] = tags
            # Word the customer is likely to use -> the menu's own category.
            for word, cat in (
                ("biryani", "Biryani & Rice"),
                ("pulao", "Biryani & Rice"),
                ("rice", "Biryani & Rice"),
                ("karahi", "Karahi & Curries"),
                ("curry", "Karahi & Curries"),
                ("bbq", "BBQ"),
                ("kabab", "BBQ"),
                ("tikka", "BBQ"),
                ("naan", "Breads"),
                ("bread", "Breads"),
                ("paratha", "Breads"),
                ("dessert", "Desserts"),
                ("sweet", "Desserts"),
                ("drink", "Drinks"),
                ("chai", "Drinks"),
                ("starter", "Starters"),
                ("side", "Sides"),
            ):
                if word in text:
                    args["category"] = cat
                    break
            return call_tool("search_menu", args)

        return say(
            "I can show you the menu, take your order, or check on an order. "
            "What would you like?"
        )


_ITEM_HINTS = {
    # Lahori Charga House
    "charga": "r1-m1", "chicken karahi": "r1-m2", "mutton karahi": "r1-m3",
    "daal": "r1-m4", "dal makhani": "r1-m4", "garlic naan": "r1-m5",
    "roghni": "r1-m6", "kachumber": "r1-m7", "raita": "r1-m8",
    "lime soda": "r1-m9",
    # Karachi Seekh & Broast
    "chicken seekh": "r2-m1", "beef seekh": "r2-m2", "seekh": "r2-m2",
    "malai boti": "r2-m3", "broast": "r2-m4", "bun kabab": "r2-m5",
    "loaded fries": "r2-m6", "paratha": "r2-m7", "mint chutney": "r2-m8",
    "water": "r2-m9",
    # Sindhi Biryani Co
    "chicken biryani": "r3-m1", "sindhi biryani": "r3-m1", "beef biryani": "r3-m2",
    "pulao": "r3-m3", "vegetable biryani": "r3-m4", "veg biryani": "r3-m4",
    "zarda": "r3-m5", "shami": "r3-m6", "salan": "r3-m8", "biryani": "r3-m1",
    # Peshawari Namak Mandi
    "namkeen": "r4-m1", "chapli": "r4-m2", "kabuli": "r4-m3",
    "lamb tikka": "r4-m4", "peshawari naan": "r4-m5", "tarkari": "r4-m6",
    "qehwa": "r4-m7", "green tea": "r4-m7", "sheer khurma": "r4-m8",
    # Chai Khana
    "doodh patti": "r5-m1", "kashmiri chai": "r5-m2", "halwa puri": "r5-m3",
    "aloo anda": "r5-m4", "nihari": "r5-m5", "gulab jamun": "r5-m6",
    "gajar": "r5-m7", "lassi": "r5-m8", "chai": "r5-m1",
}


def _guess_item(text: str) -> str | None:
    """None means 'nothing on the menu matches'.

    Returning a default here would make the model invent a dish, which is
    exactly the BC-1 failure the eval set exists to catch.
    """
    for hint, item_id in _ITEM_HINTS.items():
        if hint in text:
            return item_id
    m = re.search(r"\b(m\d{1,2})\b", text)
    return m.group(1) if m else None


def _match_line(text: str, lines: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Find the cart line the customer is referring to."""
    for line in lines:
        words = [w for w in line["name"].lower().split() if len(w) > 3]
        if any(w in text for w in words):
            return line
    return None


class FakeModel(ScriptedModel):
    """A ScriptedModel whose every step is decided by the responder above."""

    def __init__(self) -> None:
        super().__init__(
            [ModelStep(responder=_Responder()) for _ in range(12)],
            default_usage=Usage(
                requests=1, input_tokens=800, output_tokens=60, total_tokens=860
            ),
        )
