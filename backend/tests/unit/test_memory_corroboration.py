"""A diet has to be declared, not inferred.

The live failure: "show me something vegetarian" was stored as a permanent
"Vegetarian" preference. From then on the agent refused to add a chicken karahi
to that customer's order and never explained why. Browsing a category is not a
declaration, and a wrong binding memory is worse than none because it silently
removes food from every future suggestion.
"""

import pytest

from app.agent.orchestrator import _corroborated


def texts(entries):
    return [e["text"] for e in entries]


@pytest.mark.parametrize(
    "message",
    [
        "show me something vegetarian",
        "do you have vegetarian options?",
        "what is vegetarian on the menu?",
        "anything gluten free?",
        "which dishes are halal?",
    ],
)
def test_browsing_a_category_is_not_a_declaration(message):
    inferred = [{"text": "Vegetarian", "confidence": 0.9}]
    assert _corroborated(inferred, message, kind="preference") == []


@pytest.mark.parametrize(
    "message, claim",
    [
        ("I am vegetarian", "Vegetarian"),
        ("I'm vegan actually", "Vegan"),
        ("I am allergic to peanuts", "Allergic to peanuts"),
        ("we are halal", "Eats halal"),
    ],
)
def test_an_outright_declaration_is_kept(message, claim):
    kept = _corroborated([{"text": claim, "confidence": 0.9}], message, kind="preference")
    assert texts(kept) == [claim]


def test_low_stakes_memories_pass_through_uncorroborated():
    """Being wrong about a favourite costs a suggestion, not a meal."""
    entries = [
        {"text": "Likes spicy food", "confidence": 0.8},
        {"text": "Prefers to be called Ayesha", "confidence": 0.9},
        {"text": "Usually orders biryani", "confidence": 0.7},
    ]
    kept = _corroborated(entries, "show me something vegetarian", kind="preference")
    assert texts(kept) == texts(entries)


def test_a_binding_claim_is_dropped_even_beside_a_valid_one():
    entries = [
        {"text": "Likes spicy food", "confidence": 0.8},
        {"text": "Vegetarian", "confidence": 0.9},
    ]
    kept = _corroborated(entries, "show me something vegetarian", kind="preference")
    assert texts(kept) == ["Likes spicy food"]


def test_an_allergy_is_kept_when_actually_stated():
    entries = [{"text": "Allergic to shellfish", "confidence": 0.95}]
    kept = _corroborated(entries, "I am allergic to shellfish", kind="fact")
    assert texts(kept) == ["Allergic to shellfish"]


def test_an_inferred_allergy_is_dropped():
    """The most dangerous inference: never invent one from a browse."""
    entries = [{"text": "Allergic to peanuts", "confidence": 0.9}]
    assert _corroborated(entries, "does the satay have peanuts in it?", kind="fact") == []


def test_entries_without_text_are_ignored():
    assert _corroborated([{"confidence": 0.9}, {"text": ""}], "hello", kind="fact") == []
