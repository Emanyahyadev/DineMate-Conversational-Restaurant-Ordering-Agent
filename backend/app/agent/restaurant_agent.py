"""The restaurant ordering agent, built on the OpenAI Agents SDK with DeepSeek as the LLM."""

from __future__ import annotations

from functools import lru_cache

from agents import Agent, OpenAIChatCompletionsModel, Runner, set_tracing_disabled
from openai import AsyncOpenAI
from pydantic import BaseModel

from app.agent.tools import TOOLS, ChatContext
from app.config import settings

set_tracing_disabled(True)  # tracing goes to OpenAI; we run on DeepSeek

@lru_cache
def get_model() -> OpenAIChatCompletionsModel:
    """Built lazily so the app can start (and serve /health, /api/menu) without a key."""
    if not settings.deepseek_api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not set — copy .env.example to .env and fill it in.")
    client = AsyncOpenAI(api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url)
    return OpenAIChatCompletionsModel(model=settings.llm_model, openai_client=client)

SYSTEM_PROMPT = """You are the ordering assistant for a restaurant.

You can:
- show and explain the menu (use the get_menu tool, never invent dishes or prices)
- take an order (use place_order, and read the items and total back to the customer)
- check on an order (use order_status)

Style: warm, brief, and concrete. Ask one question at a time. Confirm the full order and
total before placing it. If something is not on the menu, say so and suggest the closest
alternative. Use what you know about the customer to make relevant suggestions, but never
assume an order they did not confirm.
"""


class ExtractedMemory(BaseModel):
    preferences: list[str]
    facts: list[str]


@lru_cache
def memory_extractor() -> Agent:
    return Agent(
        name="Memory Extractor",
        instructions=(
            "From the conversation turn you are given, extract durable facts worth remembering "
            "about the customer: dietary preferences, favourite dishes, allergies, name, address, "
            "spice tolerance, usual order. Write each as a short standalone sentence. "
            "Return empty lists if there is nothing durable — do not record one-off order details."
        ),
        model=get_model(),
        output_type=ExtractedMemory,
    )


def build_agent(memory: str) -> Agent:
    """Build the ordering agent with the customer's long term memory appended to the prompt."""
    return Agent(
        name="Restaurant Ordering Agent",
        instructions=f"{SYSTEM_PROMPT}\n\nWhat you know about this customer:\n{memory}",
        model=get_model(),
        tools=TOOLS,
    )


async def run_agent(memory: str, history: list[dict], user_query: str, user_id: str) -> str:
    agent = build_agent(memory)
    messages = [*history, {"role": "user", "content": user_query}]
    result = await Runner.run(agent, messages, context=ChatContext(user_id=user_id))
    return result.final_output


async def extract_memory(user_query: str, agent_response: str) -> ExtractedMemory:
    turn = f"Customer: {user_query}\nAssistant: {agent_response}"
    try:
        result = await Runner.run(memory_extractor(), turn)
        return result.final_output
    except Exception:  # memory extraction must never break the chat
        return ExtractedMemory(preferences=[], facts=[])
