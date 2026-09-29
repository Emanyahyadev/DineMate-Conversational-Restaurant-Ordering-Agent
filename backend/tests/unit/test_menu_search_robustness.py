"""The search must not tell a customer we lack a dish we are cooking.

The agent reads the tool docstring as its schema, so a stale value listed there
becomes a filter no row can satisfy - and an empty result reads to the model as
"not on the menu". That produced a live refusal for Chicken Karahi while Chicken
Karahi was on screen, so both halves are pinned here.
"""

import pytest

from app.agent import tools as tool_module
from app.services import menu_service


def category_description() -> str:
    """What the agent is told the `category` argument may be."""
    schema = tool_module.search_menu.params_json_schema
    return schema["properties"]["category"].get("description", "")


def test_the_tool_advertises_the_categories_that_actually_exist():
    """The docstring is the schema; if it drifts, the agent filters on nothing."""
    doc = category_description()
    for category in menu_service.CATEGORIES:
        assert category in doc, (
            f"search_menu does not offer {category!r}, so the agent will never "
            "filter by it"
        )


def test_no_category_is_advertised_that_does_not_exist():
    doc = category_description()
    for ghost in ("Pizza", "Pasta", "Salad"):
        assert ghost not in doc, (
            f"search_menu still advertises {ghost!r}; the agent will pass it, "
            "match nothing, and report real dishes as unavailable"
        )


@pytest.mark.anyio
async def test_an_unknown_category_widens_the_search_instead_of_emptying_it(db):
    """The exact live failure: a wrong category must not hide the dish."""
    found = await menu_service.search(db, query="chicken karahi", category="Pizza")
    assert [i["name"] for i in found][:1] == ["Chicken Karahi"]


@pytest.mark.anyio
async def test_a_real_category_still_narrows(db):
    found = await menu_service.search(db, category="Drinks", limit=12)
    assert found
    assert {i["category"] for i in found} == {"Drinks"}


@pytest.mark.anyio
@pytest.mark.parametrize(
    "query, expected",
    [
        ("chicken karahi", "Chicken Karahi"),
        ("Chicken Karahi", "Chicken Karahi"),
        ("doodh patti", "Doodh Patti Chai"),
        ("chicken charga", "Chicken Charga"),
    ],
)
async def test_a_dish_named_exactly_is_the_first_result(db, query, expected):
    found = await menu_service.search(db, query=query)
    assert found[0]["name"] == expected


@pytest.mark.anyio
async def test_a_guessed_category_cannot_hide_the_dish_that_was_named(db):
    """The live failure, exactly.

    Asked for "doodh patti" the agent guessed category=Desserts. Doodh Patti
    Chai is a drink, so the dish vanished and Zarda was offered in its place.
    A dish the customer named by name outranks a course the agent guessed.
    """
    found = await menu_service.search(db, query="doodh patti", category="Desserts")
    assert found[0]["name"] == "Doodh Patti Chai"


@pytest.mark.anyio
async def test_nothing_found_looks_like_nothing_found(db):
    """Returning unrelated dishes let the agent pass them off as near-misses."""
    assert await menu_service.search(db, query="sushi") == []


@pytest.mark.anyio
async def test_browsing_a_category_still_narrows_to_it(db):
    found = await menu_service.search(db, category="Drinks", limit=12)
    assert found and {i["category"] for i in found} == {"Drinks"}


@pytest.mark.anyio
async def test_a_category_that_fits_the_query_is_respected(db):
    found = await menu_service.search(
        db, query="chicken karahi", category="Karahi & Curries", limit=6
    )
    assert found[0]["name"] == "Chicken Karahi"
    assert {i["category"] for i in found} == {"Karahi & Curries"}


@pytest.mark.anyio
async def test_a_vague_query_still_returns_suggestions(db):
    found = await menu_service.search(db, query="something spicy", limit=4)
    assert found, "a browsing query should still suggest dishes"
