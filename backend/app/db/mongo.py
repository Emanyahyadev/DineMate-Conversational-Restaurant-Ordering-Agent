"""Long term memory: personal preferences and personal data stored in MongoDB."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient

from app.config import settings

client = AsyncIOMotorClient(settings.mongodb_url)
db = client[settings.mongodb_db]
profiles = db["profiles"]


async def get_profile(user_id: str) -> dict[str, Any]:
    profile = await profiles.find_one({"_id": user_id})
    return profile or {"_id": user_id, "preferences": [], "facts": []}


async def profile_summary(user_id: str) -> str:
    """A compact text block appended to the system prompt."""
    profile = await get_profile(user_id)
    preferences = profile.get("preferences", [])
    facts = profile.get("facts", [])
    if not preferences and not facts:
        return "No long term memory for this customer yet."
    lines = []
    if preferences:
        lines.append("Preferences: " + "; ".join(preferences))
    if facts:
        lines.append("Personal info: " + "; ".join(facts))
    return "\n".join(lines)


async def remember(user_id: str, preferences: list[str], facts: list[str]) -> None:
    """Append newly extracted memories, de-duplicated."""
    if not preferences and not facts:
        return
    await profiles.update_one(
        {"_id": user_id},
        {
            "$addToSet": {
                "preferences": {"$each": preferences},
                "facts": {"$each": facts},
            },
            "$set": {"updated_at": datetime.now(timezone.utc)},
        },
        upsert=True,
    )
