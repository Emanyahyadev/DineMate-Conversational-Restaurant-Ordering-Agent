# Observability

**Version:** 1.0.0 · OpenTelemetry → OTLP collector → traces, metrics, logs.

Every KPI in [KPIS.md](KPIS.md) marked `otel` is computed from what this document specifies. If a
KPI has no span attribute or metric here, it cannot be measured — so this file and that one are
maintained together.

---

## 1. Principle

**One trace per turn.** A turn is the unit customers experience and the unit that costs money, so it
is the unit of observation. Given a trace id you can answer: what did the customer ask, which
prompt version ran, which tools were called with what arguments, what the model returned, how long
each part took, what it cost — without reading a single log line.

---

## 2. Trace structure

```
chat.turn                                    ← root, one per POST /api/chat
├── auth.verify                              (~2 ms)
├── context.assemble
│   ├── memory.profile_summary               ← P05
│   └── db.messages.recent                   ← P04
├── agent.run
│   ├── llm.call (attempt 1)                 ← R03, C02, C03
│   ├── tool.search_menu
│   │   └── db.query
│   ├── llm.call (attempt 2)
│   └── tool.add_to_cart
│       └── db.transaction
├── stream.first_token                       ← P01 marker
├── persist.turn
└── memory.extract                           ← off critical path, C05
    └── llm.call
```

`X-Request-Id` on every response **equals the trace id**, so a customer complaint or a support
ticket resolves to the exact trace with no correlation step.

### Root span `chat.turn`

| Attribute | Example | Feeds |
| --- | --- | --- |
| `user.id` | uuid | tenancy audit |
| `conversation.id` | uuid | |
| `message.id` | 9013 | joins to `messages` |
| `prompt.version` | `v1.0.0` | attribution ([AGENT_SPEC.md](AGENT_SPEC.md) §8) |
| `turn.duration_ms` | 2310 | P02 |
| `turn.ttft_ms` | 840 | **P01** |
| `turn.llm_ms` | 2180 | |
| `turn.overhead_ms` | 130 | **P03** = duration − llm_ms |
| `turn.tool_count` | 2 | C04 |
| `turn.cost_cents` | 0.31 | C01 |
| `turn.outcome` | `done` \| `error` | R02 |
| `degraded.memory` | true/false | R06 |

### `llm.call`
`llm.model`, `llm.temperature`, `llm.prompt_tokens` (**C02**), `llm.completion_tokens` (C03),
`llm.duration_ms`, `llm.attempt`, `llm.finish_reason`, `llm.cost_cents`, `llm.purpose`
(`agent` | `extraction` — this is what splits C05).

**Never recorded:** full prompt or completion text. Reasons in §4.

### `tool.<name>`
`tool.name`, `tool.duration_ms`, `tool.outcome` (`ok` | `error`), `tool.error_code`,
`tool.args_digest` (SHA-256 of normalised arguments — comparable across turns without storing
content), and the mutation markers `cart.version_after`, `order.id`, `confirmation.token_consumed`.

That last attribute is how **A01** is measured in production: a `confirm_order` span with
`confirmation.token_consumed = false` is a violation, and it is impossible by construction — so the
metric doubles as a check that the construction still holds after a refactor.

### `db.*`
`db.statement` (parameterised text only, **never** values), `db.duration_ms` (**P04**), `db.rows`.

---

## 3. Metrics

RED for endpoints plus the KPI-specific series.

| Metric | Type | Labels | KPI |
| --- | --- | --- | --- |
| `http.server.duration` | histogram | route, status | R01, R02 |
| `chat.turns` | counter | outcome | R02 |
| `chat.ttft` | histogram | — | **P01** |
| `chat.duration` | histogram | — | P02 |
| `chat.overhead` | histogram | — | **P03** |
| `llm.calls` | counter | model, purpose, outcome, attempt | R03 |
| `llm.tokens` | histogram | direction, purpose | C02, C03 |
| `llm.cost_cents` | counter | model, purpose | C01, C05 |
| `tool.calls` | counter | name, outcome, error_code | R04, C04 |
| `db.query.duration` | histogram | operation | P04 |
| `memory.read.duration` | histogram | — | P05 |
| `orders.confirmed` | counter | fulfilment | R05, B01 |
| `orders.cancelled` | counter | reason_class | B03 |
| `agent.violations` | counter | **kind** (`unauthorized_action`, `hallucination`, `leakage`) | **A01, A02, A03** |
| `auth.refresh_reuse` | counter | — | security page |
| `degraded.mode` | gauge | dependency | R06 |

`agent.violations` is the one to watch: it should be flat at zero forever, and any non-zero value
pages.

### Online scorers
A background consumer samples completed turns (10% of all, **100%** of turns that confirmed an
order) and runs the deterministic `grounding` and `unauthorized_action` scorers from
[EVAL_PLAN.md](EVAL_PLAN.md) §3 against the span tree, incrementing `agent.violations`. Same code
path as the eval scorers — one implementation, so CI and production cannot disagree about what a
violation is.

---

## 4. Logging and PII

Structured JSON to stdout. Every line carries `trace_id`, `span_id`, `user_id`, `level`, `event`.

**Never logged:** message content, prompt text, completion text, passwords, tokens (access, refresh,
reset, confirmation), email addresses, raw IPs, order notes.

**Rationale for excluding message content.** It is the single most useful thing for debugging and
the single most dangerous thing to retain — customer conversations contain names, addresses, and
health information (allergies). Debugging uses the span tree: tool names, argument digests, error
codes, and timings identify almost every real failure. When content is genuinely required, a
time-boxed, per-user, explicitly-enabled `debug.capture` flag writes to a 24-hour store, and turning
it on is an audited action.

A CI check greps for banned patterns (`logger.*message`, `logger.*prompt`, `logger.*password`) and
fails the build.

| Level | Use |
| --- | --- |
| ERROR | Unexpected exception, dependency failure, invariant violation |
| WARN | Degraded mode, LLM retry, rate limit hit, tool error returned to the model |
| INFO | Turn start/end, order confirmed/cancelled, auth events |
| DEBUG | Local only; never enabled in production |

---

## 5. Dashboards

Panels map 1:1 to [KPIS.md](KPIS.md); no panel exists without a KPI, and no KPI lacks a panel.

**Agent Quality** — `agent.violations` by kind (must be flat zero) · A04/A05 from the latest eval
run · tool-call distribution · error codes by tool · memory writes per 100 turns.

**Reliability** — availability · chat success rate (R02) · LLM success and retry rate (R03) · tool
error rate (R04) · degraded-mode gauge · order reconciliation status (R05).

**Performance** — TTFT p50/p95 (P01) · full duration (P02) · **overhead vs. LLM time stacked**
(P03 — the panel that says whether a slowdown is ours or the model's) · DB p95 by operation ·
memory read p95 · concurrent turns.

**Cost** — cost per conversation (C01) · daily spend with the monthly budget line · prompt tokens
p95 against the 4 000 budget (C02) · agent vs. extraction split (C05).

**Product** (TREND) — conversion (B01) · turns to confirm (B02) · cancellation rate (B03) · memory
hit rate (B04) · abandonment after read-back (B05).

---

## 6. Alerts

Routing and thresholds are in [KPIS.md](KPIS.md) §7. Discipline:

- **Every page has a runbook entry** ([RUNBOOK.md](RUNBOOK.md) §8). A page with no documented first
  action is an alert that will be ignored at 3am.
- **Every page is actionable.** If the responder can only say "yes, that is happening", it becomes a
  ticket instead.
- **Symptom-based, not cause-based.** Alert on "chat error rate > 1%", not "Mongo CPU high" — the
  latter fires during harmless spikes and stays silent during novel failures.
- Alert fatigue is tracked: > 2 non-actionable pages in a week triggers a threshold review.

---

## 7. Sampling and retention

| Data | Sampling | Retention |
| --- | --- | --- |
| Traces (normal) | 10% | 30 days |
| Traces (error / order confirmed / violation) | **100%** | 90 days |
| Metrics | all | 13 months (year-over-year) |
| Logs (INFO+) | all | 30 days |
| Eval scorecards | all | forever (small, and they are the prompt's history) |

Head sampling is a lie for errors — you cannot know a turn was interesting before it finishes — so
the collector uses **tail sampling**: keep everything that errored, confirmed an order, exceeded the
P02 budget, or raised a violation.

---

## 8. Local development

`docker compose up` starts an OTLP collector plus a trace viewer. `OTEL_ENABLED=false` disables
everything for a fast unit-test loop. Traces render in the terminal on demand
(`OTEL_CONSOLE_EXPORTER=true`), which makes "which tool did it actually call?" a five-second
question during development — the same question the eval scorers ask, answered the same way.
