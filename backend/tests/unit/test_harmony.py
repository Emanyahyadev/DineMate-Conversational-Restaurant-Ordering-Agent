"""Repairing harmony-format leakage.

The live failure: gpt-oss named a tool ``view_cart<|channel|>commentary``, the
SDK could not find it, and the turn died - so the agent would find a dish and
then never manage to order it. These pin the repair, and pin the limits of it.
"""

import pytest

from app.agent.harmony import clean_tool_name, repair_event, strip_control_tokens


class Item:
    def __init__(self, name, type="function_call"):
        self.name = name
        self.type = type


class Event:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


@pytest.mark.parametrize(
    "mangled, expected",
    [
        ("view_cart<|channel|>commentary", "view_cart"),
        ("add_to_cart<|channel|>commentary", "add_to_cart"),
        ("search_menu<|constrain|>json", "search_menu"),
        ("confirm_order<|end|>", "confirm_order"),
        ("get_full_menu ", "get_full_menu"),
        # Already clean names are untouched.
        ("view_cart", "view_cart"),
        ("update_cart_item", "update_cart_item"),
        ("", ""),
    ],
)
def test_tool_names_are_repaired(mangled, expected):
    assert clean_tool_name(mangled) == expected


def test_a_genuinely_wrong_tool_name_is_not_rescued():
    """The repair must not invent a valid name out of an invalid one."""
    assert clean_tool_name("place_the_order") == "place_the_order"
    assert clean_tool_name("nonsense") == "nonsense"


@pytest.mark.parametrize(
    "text, expected",
    [
        ("<|channel|>commentary Here is the menu", "commentary Here is the menu"),
        ("Rs 1,650<|end|>", "Rs 1,650"),
        ("plain text", "plain text"),
        ("", ""),
    ],
)
def test_control_tokens_never_reach_the_customer(text, expected):
    assert strip_control_tokens(text) == expected


def test_an_item_event_is_repaired():
    event = Event(item=Item("add_to_cart<|channel|>commentary"))
    repair_event(event)
    assert event.item.name == "add_to_cart"


def test_the_assembled_response_is_repaired_too():
    """Both routes matter: fixing only the item events leaves the failure."""
    response = Event(output=[Item("view_cart<|channel|>commentary"), Item("ok")])
    event = Event(response=response)
    repair_event(event)
    assert [o.name for o in event.response.output] == ["view_cart", "ok"]


def test_a_non_tool_item_is_left_alone():
    event = Event(item=Item("some|text", type="message"))
    repair_event(event)
    assert event.item.name == "some|text"


def test_text_deltas_are_cleaned():
    event = Event(delta="<|channel|>final Chicken Karahi")
    repair_event(event)
    assert event.delta == "final Chicken Karahi"


def test_an_event_with_nothing_to_repair_survives():
    event = Event(delta="Rs 1,650")
    assert repair_event(event) is event
    assert event.delta == "Rs 1,650"


class Fn:
    def __init__(self, name):
        self.name = name


class Call:
    def __init__(self, name):
        self.function = Fn(name)


class Delta:
    def __init__(self, tool_calls=None, content=None):
        self.tool_calls = tool_calls
        self.content = content


class Choice:
    def __init__(self, delta):
        self.delta = delta


class Chunk:
    def __init__(self, *choices):
        self.choices = list(choices)


def test_a_raw_chunk_has_its_tool_name_repaired():
    """The chunk is the earliest point the mangled name exists, and the only
    one early enough to fix tool resolution."""
    from app.agent.harmony import repair_chunk

    chunk = Chunk(Choice(Delta(tool_calls=[Call("search_menu<|channel|>analysis")])))
    repair_chunk(chunk)
    assert chunk.choices[0].delta.tool_calls[0].function.name == "search_menu"


def test_a_raw_chunk_has_its_content_cleaned():
    from app.agent.harmony import repair_chunk

    chunk = Chunk(Choice(Delta(content="<|channel|>final Rs 150")))
    repair_chunk(chunk)
    assert chunk.choices[0].delta.content == "final Rs 150"


def test_a_chunk_with_no_delta_survives():
    from app.agent.harmony import repair_chunk

    chunk = Chunk(Choice(None))
    assert repair_chunk(chunk) is chunk


def test_an_empty_chunk_survives():
    from app.agent.harmony import repair_chunk

    chunk = Chunk()
    assert repair_chunk(chunk) is chunk
