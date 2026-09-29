"""Deterministic memory extraction.

The LLM extractor in ``orchestrator`` is the richer path, but it is a second
model call: on a slow provider it can take minutes, and it runs after the
response has already closed. Memory that only lands sometimes is worse than no
memory, because the customer cannot tell which.

So the rules below run first, synchronously, on every turn. They are narrow and
literal - they only fire on phrasings that state a durable fact outright - and
the model pass adds whatever they miss. Precision over recall, as KPI A08a
requires (AGENT_SPEC.md section 6).
"""

from __future__ import annotations

import re
from typing import Any

ALLERGENS = [
    "peanut",
    "tree nut",
    "nut",
    "dairy",
    "milk",
    "egg",
    "gluten",
    "wheat",
    "soy",
    "shellfish",
    "prawn",
    "fish",
    "sesame",
]

DIETS = {
    "vegetarian": "Vegetarian",
    "vegan": "Vegan",
    "pescatarian": "Pescatarian",
    "halal": "Eats halal",
    "kosher": "Eats kosher",
    "gluten free": "Eats gluten free",
    "gluten-free": "Eats gluten free",
    "dairy free": "Eats dairy free",
    "dairy-free": "Eats dairy free",
}

# "I am allergic to peanuts", "allergic to peanuts and shellfish",
# "I have a nut allergy".
#
# The list stops at a clause boundary. Without that, "allergic to peanuts and I
# am vegetarian" swallowed the second clause and stored the fact
# "Allergic to I am vegetarian" - a wrong memory, which is worse than none
# because it silently shapes every later suggestion.
_ALLERGY_ITEM = r"(?:(?!\b(?:i|we|but|though|so|because|however)\b)[a-z])+"
_ALLERGY = re.compile(
    rf"\ballergic\s+to\s+((?:{_ALLERGY_ITEM}|\s|,|\band\b)+)|"
    r"\bi\s+have\s+an?\s+([a-z ]+?)\s+allerg(?:y|ies)\b",
    re.I,
)

# "I'm vegetarian", "I am vegan", "we are halal"
_DIET = re.compile(
    r"\b(?:i(?:'m| am)|we(?:'re| are)|im)\s+(?:a\s+|an\s+)?"
    r"(vegetarian|vegan|pescatarian|halal|kosher|gluten[- ]free|dairy[- ]free)\b",
    re.I,
)

# "My name is Nadia", "call me Nadia". Case-insensitive on the lead-in, because
# a sentence-initial "My" is the common case and would otherwise never match.
_NAME = re.compile(
    r"\bmy\s+name\s+is\s+([A-Za-z][a-z]{1,20})\b|\bcall\s+me\s+([A-Za-z][a-z]{1,20})\b",
    re.I,
)

# A phrase runs until a conjunction or punctuation. Without this,
# "I love spicy food but I don't eat pork" stores "Likes spicy food but I do".
_PHRASE = r"((?:(?!\b(?:but|and|though|however|because)\b)[a-z ])+)"

# "I don't eat pork", "I can't eat dairy"
_AVOID = re.compile(r"\bi\s+(?:do\s?n'?t|cannot|can'?t|won'?t)\s+eat\s+" + _PHRASE, re.I)

# "I love spicy food", "I hate coriander"
_LIKE = re.compile(r"\bi\s+(love|really like|hate|cannot stand)\s+" + _PHRASE, re.I)

MAX_PHRASE = 24


def _clean(text: str) -> str:
    """Normalise whitespace and drop dangling punctuation or conjunctions.

    A clause that stops mid-list leaves "peanuts and"; storing that as the
    allergen reads badly everywhere it is later shown.
    """
    text = re.sub(r"\s+", " ", text).strip(" .,!")
    text = re.sub(r"^(?:and|or)\s+", "", text, flags=re.I)
    text = re.sub(r"\s+(?:and|or)$", "", text, flags=re.I)
    return text.strip()


def extract(message: str) -> dict[str, list[dict[str, Any]]]:
    """Pull durable facts out of one customer message. Never raises."""
    facts: list[dict[str, Any]] = []
    preferences: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(bucket: list[dict[str, Any]], text: str, **extra: Any) -> None:
        key = text.lower()
        if key in seen:
            return
        seen.add(key)
        bucket.append({"text": text, "confidence": 0.95, **extra})

    for match in _ALLERGY.finditer(message):
        raw = _clean(match.group(1) or match.group(2) or "")
        if not raw:
            continue
        # Split "peanuts and shellfish" into separate facts.
        for part in re.split(r",| and ", raw):
            part = _clean(part).removeprefix("and ").strip()
            if (part and any(a in part.lower() for a in ALLERGENS)) or (part and len(part) < 24):
                add(facts, f"Allergic to {part}", kind="allergy")

    for match in _DIET.finditer(message):
        key = match.group(1).lower().replace("-", " ")
        add(preferences, DIETS.get(key, key.capitalize()))

    for match in _NAME.finditer(message):
        name = match.group(1) or match.group(2)
        if name and name.lower() not in ("dinemate", "sorry", "sure"):
            add(facts, f"Prefers to be called {name}", kind="name")

    for match in _AVOID.finditer(message):
        what = _clean(match.group(1))
        if what and len(what) <= MAX_PHRASE:
            add(preferences, f"Does not eat {what}")

    for match in _LIKE.finditer(message):
        verb, what = match.group(1).lower(), _clean(match.group(2))
        if not what or len(what) > MAX_PHRASE:
            continue
        if verb in ("love", "really like"):
            add(preferences, f"Likes {what}")
        else:
            add(preferences, f"Dislikes {what}")

    return {"preferences": preferences, "facts": facts}
