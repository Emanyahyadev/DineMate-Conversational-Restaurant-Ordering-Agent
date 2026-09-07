# ADR-0006 — DeepSeek v4 Pro via NVIDIA misses the latency KPI by ~40x

**Status:** Resolved — model switched · **Date:** 2026-09-07

## Context

The owner supplied an NVIDIA-hosted DeepSeek endpoint:

```
base_url = https://integrate.api.nvidia.com/v1
model    = deepseek-ai/deepseek-v4-pro-0813
```

This is wired into `backend/.env` and works. Measured on this machine, warm, with
`chat_template_kwargs: {thinking: false}` and streaming enabled:

| What | Time to first token |
| --- | --- |
| "Say exactly: DineMate online", 64 max tokens | 103 s |
| "Reply with only the number 1", 48 max tokens | 170 s |
| Same prompt, second call | 142 s |
| Same prompt, third call | 104 s |
| **One agent turn** ("What vegetarian mains do you have?", 3 tool calls) | **867 s** |

[KPIS.md](../KPIS.md) P01 requires **TTFT p95 ≤ 2.5 s**. The measured floor is roughly **40–70x**
over budget, and a full tool-using turn is ~350x over the P02 budget of 8 s.

**Quality, separately, is good.** On the live turn the agent called `search_menu` three times,
named only real dishes, quoted `$9.50` exactly as the tool returned it, correctly identified
Margherita as the only vegetarian main, and asked before adding anything — no BC-1/BC-2/BC-3
violation. The problem is purely latency.

## Diagnosis

Consistent 100 s+ TTFT on a 5-token completion is not generation time; it is queueing. The
`integrate.api.nvidia.com` endpoint is a shared evaluation tier. Latency did not improve across
consecutive calls, so it is not a cold start.

## Resolution (2026-09-07)

The same NVIDIA key hosts other models. Measured, warm, with the real DineMate
tool set and system prompt:

| Model | First token | Tool calling |
| --- | --- | --- |
| `deepseek-ai/deepseek-v4-pro-0813` | 104–465 s | worked, but often returned an empty completion |
| `nvidia/nemotron-3-super-120b-a12b` | 9.7 s | correct |
| `nvidia/nemotron-3.5-lightning-30b-a3b` | 5.7 s | correct |
| **`openai/gpt-oss-20b`** | **1.6 s** | correct |

`LLM_MODEL` is now `openai/gpt-oss-20b`. A full turn (tool call plus reply) takes
roughly 30–60 s end to end, which is dominated by the shared endpoint's queueing,
not by DineMate: `P03` (backend overhead excluding the LLM) stays inside its
150 ms budget.

**P01 and P02 are still failing** and remain recorded as such. Meeting them needs
a dedicated inference endpoint; nothing in the application code stands in the way,
and switching is one line in `.env`.

## Options considered

1. **Different host, same model family.** DeepSeek's own API, or any dedicated inference provider.
   Cheapest change: `DEEPSEEK_BASE_URL` + `DEEPSEEK_API_KEY`, no code.
2. **Smaller/faster model** for the ordering loop. Tool selection is not a reasoning task;
   [KPIS.md](../KPIS.md) A04/A05 are what matter and a mid-size model may well hit them.
3. **Accept and reshape the UX** — a background "we are working on your order" model. This is a
   different product, and it is not what [PRD.md](../PRD.md) §4 describes.

**Recommendation: option 1.** The provider is one config line and the code is already
provider-agnostic ([ADR-0001](0001-agents-sdk-deepseek.md)).

## Status of the KPI

P01 and P02 are **failing** against this endpoint and are recorded as such. They are not waived.
Nothing else in the system is implicated: `P03` (backend overhead excluding the LLM) is unaffected,
and the eval suite runs against a deterministic fake model, so accuracy gates are unaffected too.
