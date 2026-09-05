# ADR-0001 — OpenAI Agents SDK on DeepSeek

**Status:** Accepted · **Date:** 2026-09-06 · **Deciders:** Project owner

## Context

The agent needs reliable tool calling, structured outputs, and streaming. The architecture brief
specifies the OpenAI Agents SDK as the framework and DeepSeek as the model. Both were validated in
the scaffold before this decision was written down.

## Decision

Use the **OpenAI Agents SDK** as the agent runtime, pointed at **DeepSeek** through its
OpenAI-compatible endpoint via `OpenAIChatCompletionsModel` with a custom `AsyncOpenAI` client.

Consequences captured in the scaffold and carried forward:

- `set_tracing_disabled(True)` — the SDK's built-in tracing uploads to OpenAI, which is not our
  provider. Observability is OpenTelemetry instead ([OBSERVABILITY.md](../OBSERVABILITY.md)).
- The model client is built **lazily** (`get_model()` in `backend/app/agent/restaurant_agent.py`) so
  the app boots and serves `/health` and `/api/menu` without an API key.
- Tool context flows via `RunContextWrapper[ChatContext]`, which is what keeps `user_id` out of the
  model's reach ([AUTH_SPEC.md](../AUTH_SPEC.md) §5).

## Alternatives considered

**LangChain / LangGraph** — more capable graph orchestration than this domain needs; heavier
dependency surface; the SDK's tool-context mechanism maps directly onto our trust boundary.

**Direct API calls, no framework** — maximum control, but we would hand-roll tool-call parsing,
retries, and structured output. The SDK's abstraction is thin enough to reason about.

**OpenAI or Anthropic models** — stronger tool-calling track record, higher cost. DeepSeek's
OpenAI-compatible API means swapping is a one-line config change if
[KPIS.md](../KPIS.md) A04/A05 cannot be met — the exit gate at M3 is where that decision gets made
with data.

## Consequences

**Good:** provider-swappable behind one config value; tool schemas generated from Python signatures;
run context gives a first-class trusted channel for identity.

**Bad:** the SDK is young and its API may shift — pinned in `uv.lock`, upgraded deliberately. Some
SDK behaviour assumes OpenAI (tracing, some model params); we disable rather than fight it.

**Risk:** DeepSeek changing behaviour under a stable model id. Mitigated by a nightly live eval run
and a scorecard per prompt version — detection within 24 hours.
