"""Long-term memory in MongoDB. Implements Rules N1-N5 (DOMAIN_MODEL.md).

Mongo being unreachable is a degradation, not a failure: every read here
returns an empty profile rather than raising (ARCHITECTURE.md section 6, KPI R06).
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from pymongo.errors import PyMongoError

from app.config import settings
from app.db.mongo import profiles

logger = logging.getLogger(__name__)

MAX_MEMORY_TOKENS_CHARS = 1200  # ~300 tokens (ARCHITECTURE.md section 4)

# Rule N2 / INV-10: never store these, whatever the extractor proposes.
DENY_PATTERNS = [
    re.compile(r"\b(?:\d[ -]*?){13,19}\b"),  # card numbers
    re.compile(r"\b(cvv|cvc|pin|password|passcode)\b", re.I),
    re.compile(r"\b(ssn|social security|passport|licence|license|national id)\b", re.I),
    re.compile(r"\b(credit|debit)\s+card\b", re.I),
    re.compile(r"\b(iban|sort code|routing number|account number)\b", re.I),
    re.compile(r"\b(diagnos|medication|prescription|disease|depress|anxiet|pregnan)\w*", re.I),
    re.compile(r"\b\d{1,4}\s+\w+\s+(street|st|road|rd|avenue|ave|lane|ln)\b", re.I),
    re.compile(r"\b(lat|lng|latitude|longitude)\b", re.I),
]

ALLERGY_HINT = re.compile(r"\ballerg|anaphyla|intoleran", re.I)


def is_denied(text: str) -> bool:
    """Allergies are the one health-adjacent thing we do keep (Rule N3)."""
    if ALLERGY_HINT.search(text):
        return any(p.search(text) for p in DENY_PATTERNS[:5])
    return any(p.search(text) for p in DENY_PATTERNS)


ALLERGEN_WORDS = [
    "peanut", "tree nut", "nut", "dairy", "milk", "egg", "gluten", "wheat",
    "soy", "shellfish", "prawn", "fish", "sesame",
]


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


DIET_WORDS = [
    "vegetarian",
    "vegan",
    "pescatarian",
    "halal",
    "kosher",
    "gluten free",
    "dairy free",
]


def _dedupe_key(text: str, kind: str | None = None) -> str:
    """Collapse two phrasings of the same fact onto one key.

    Two passes write memory: fast rules ("Vegetarian") and the model ("The
    customer follows a vegetarian diet."). Keyed on raw text those are two
    entries, so the customer sees the same fact twice, the prompt budget pays
    for it twice, and deleting one leaves the other behind.

    A customer has one name, and one entry per allergen and per diet.
    """
    low = text.lower()

    if kind == "name" or low.startswith("prefers to be called"):
        return "name"

    if kind == "allergy" or "allerg" in low:
        for word in sorted(ALLERGEN_WORDS, key=len, reverse=True):
            if word in low:
                return f"allergy:{word}"

    for word in sorted(DIET_WORDS, key=len, reverse=True):
        if word in low:
            return f"diet:{word}"

    return _normalise(text)


async def get_profile(user_id: str) -> dict[str, Any]:
    try:
        doc = await profiles.find_one({"_id": user_id})
    except PyMongoError as exc:
        logger.warning("memory unavailable for %s: %s", user_id, exc)
        return {"_id": user_id, "preferences": [], "facts": [], "degraded": True}
    return doc or {"_id": user_id, "preferences": [], "facts": []}


async def profile_summary(user_id: str) -> str:
    """Rendered into the prompt as quoted data, never as instruction (Rule N5).

    Allergies are emitted first and are never dropped by the character budget.
    """
    profile = await get_profile(user_id)
    facts = profile.get("facts", [])
    prefs = profile.get("preferences", [])

    allergies = [f for f in facts if f.get("kind") == "allergy"]
    other_facts = [f for f in facts if f.get("kind") != "allergy"]

    lines: list[str] = []
    if allergies:
        lines.append("ALLERGIES (binding): " + "; ".join(f["text"] for f in allergies))

    budget = MAX_MEMORY_TOKENS_CHARS - sum(len(line) for line in lines)
    tail: list[str] = []
    if other_facts:
        tail.append("Personal info: " + "; ".join(f["text"] for f in other_facts))
    if prefs:
        ordered = sorted(prefs, key=lambda p: p.get("confidence", 0), reverse=True)
        tail.append("Preferences: " + "; ".join(p["text"] for p in ordered))
    for line in tail:
        if budget - len(line) < 0:
            break
        lines.append(line)
        budget -= len(line)

    if not lines:
        return "Nothing on file for this customer yet."
    return "\n".join(lines)


async def known_allergens(user_id: str) -> list[str]:
    """The allergens on file, as menu vocabulary.

    Rule N3: this is applied to every menu search server-side, so the model
    forgetting to pass an exclusion cannot produce an unsafe suggestion.
    """
    profile = await get_profile(user_id)
    found: list[str] = []
    for fact in profile.get("facts", []):
        if fact.get("kind") != "allergy":
            continue
        low = (fact.get("text") or "").lower()
        # Longest first, so "peanut" wins over "nut" and the pair is not doubled.
        for word in sorted(ALLERGEN_WORDS, key=len, reverse=True):
            if word in low and not any(word in seen for seen in found):
                found.append(word)
    return found


async def remember(
    user_id: str,
    preferences: list[dict[str, Any]],
    facts: list[dict[str, Any]],
) -> int:
    """Append with dedupe, above the confidence floor, past the deny-list."""
    floor = settings.memory_confidence_floor
    profile = await get_profile(user_id)
    if profile.get("degraded"):
        return 0

    existing = {
        _dedupe_key(e["text"], e.get("kind"))
        for e in list(profile.get("preferences", [])) + list(profile.get("facts", []))
    }

    new_prefs, new_facts, now = [], [], datetime.now(timezone.utc)
    for p in preferences:
        text = str(p.get("text", "")).strip()[:120]
        if not text or p.get("confidence", 0) < floor or is_denied(text):
            continue
        if _dedupe_key(text) in existing:
            continue
        existing.add(_dedupe_key(text))
        new_prefs.append(
            {
                "id": f"p_{uuid.uuid4().hex[:8]}",
                "text": text,
                "confidence": float(p.get("confidence", 0)),
                "created_at": now,
                "last_seen_at": now,
            }
        )

    for f in facts:
        text = str(f.get("text", "")).strip()[:120]
        if not text or f.get("confidence", 0) < floor or is_denied(text):
            continue
        kind = f.get("kind", "other")
        if _dedupe_key(text, kind) in existing:
            continue
        existing.add(_dedupe_key(text, kind))
        new_facts.append(
            {
                "id": f"f_{uuid.uuid4().hex[:8]}",
                "text": text,
                "kind": kind,
                "confidence": float(f.get("confidence", 0)),
                "created_at": now,
            }
        )

    if not new_prefs and not new_facts:
        return 0

    try:
        await profiles.update_one(
            {"_id": user_id},
            {
                "$push": {"preferences": {"$each": new_prefs}, "facts": {"$each": new_facts}},
                "$set": {"updated_at": now, "schema_version": 1},
            },
            upsert=True,
        )
    except PyMongoError as exc:
        logger.warning("memory write failed for %s: %s", user_id, exc)
        return 0
    return len(new_prefs) + len(new_facts)


async def list_memories(user_id: str) -> dict[str, Any]:
    """US-24: the customer can see everything stored about them."""
    profile = await get_profile(user_id)
    clean = lambda items: [  # noqa: E731
        {
            "id": i.get("id"),
            "text": i.get("text"),
            "kind": i.get("kind"),
            "created_at": i["created_at"].isoformat() if i.get("created_at") else None,
        }
        for i in items
    ]
    return {
        "preferences": clean(profile.get("preferences", [])),
        "facts": clean(profile.get("facts", [])),
    }


async def forget(user_id: str, memory_id: str) -> bool:
    """US-24: and delete any of them."""
    try:
        result = await profiles.update_one(
            {"_id": user_id},
            {
                "$pull": {
                    "preferences": {"id": memory_id},
                    "facts": {"id": memory_id},
                }
            },
        )
    except PyMongoError as exc:
        logger.warning("memory delete failed for %s: %s", user_id, exc)
        return False
    return result.modified_count > 0


async def forget_all(user_id: str) -> None:
    try:
        await profiles.delete_one({"_id": user_id})
    except PyMongoError as exc:
        logger.warning("memory purge failed for %s: %s", user_id, exc)


async def ping() -> bool:
    try:
        await profiles.database.command("ping")
        return True
    except PyMongoError:
        return False
