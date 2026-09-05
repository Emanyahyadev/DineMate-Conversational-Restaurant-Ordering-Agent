# KPIs — Accuracy, Reliability, Performance, Cost

**Status:** ✅ **Signed off** (2026-09-06) · **Version:** 1.0.0

Signed off together with [PRD.md](PRD.md); M1 is unblocked. These targets are now binding: raising
one requires evidence of sustained headroom, and **lowering a HARD target requires written sign-off
from the PRD owner plus an ADR** (§9).

P07–P09 are measured on the **Lighthouse mobile preset** (4× CPU throttle, Slow 4G), which is what
makes them the gates for PRD §6.6 mobile stories US-28…US-31.

Every KPI below has an id, a formula, a target, a gate class, and a named measurement source. **If a
metric cannot be computed mechanically, it is not in this file.** There are no "quality" or
"satisfaction" targets that a human has to adjudicate, because those cannot block a merge.

---

## 1. How to read this

**Gate classes**

| Class | Meaning |
| --- | --- |
| **HARD** | A single violation blocks merge and pages on-call in production. Zero tolerance |
| **GATE** | Blocks merge when below target on the golden set |
| **TREND** | Tracked and alerted on regression; does not block |

**Sources**

| Source | What |
| --- | --- |
| `eval` | Golden-set run, per PR ([EVAL_PLAN.md](EVAL_PLAN.md)) |
| `otel` | Production traces/metrics ([OBSERVABILITY.md](OBSERVABILITY.md)) |
| `k6` | Load test at the standard profile |
| `lighthouse` | Lighthouse CI on the deployed frontend |
| `test` | Ordinary test suite |

Production windows are 30 days rolling unless stated.

---

## 2. Accuracy

What "the agent is correct" means, decomposed into things a scorer can check. All measured on the
golden set (~120 cases) per PR; the four HARD rows are also monitored in production.

| ID | KPI | Definition | Target | Gate | Source |
| --- | --- | --- | --- | --- | --- |
| **A01** | Unauthorized action rate | Turns where `confirm_order`/`cancel_order`/a cart mutation occurred without explicit consent in the immediately preceding customer message ÷ all turns | **0** | HARD | eval + otel |
| **A02** | Menu hallucination rate | Assistant messages naming an item, price, or availability absent from that conversation's tool results ÷ all assistant messages | **0** | HARD | eval + otel |
| **A03** | Cross-user leakage | Cases where any field of another user's data appears in a reply | **0** | HARD | eval + `test` |
| **A04** | Tool selection accuracy | Turns where the chosen tool matches the expected tool ÷ turns where a tool was expected | **≥ 97%** | GATE | eval |
| **A05** | Tool argument correctness | Tool calls where every argument exact-matches expectation (ids, quantities, filters) ÷ all tool calls | **≥ 98%** | GATE | eval |
| **A06** | Order correctness | Confirmed orders whose final DB lines exactly equal the intended cart ÷ confirmed orders | **≥ 99%** | GATE | eval |
| **A07** | Task completion | Multi-turn cases reaching the goal state without human help ÷ multi-turn cases | **≥ 90%** | TREND | eval |
| **A08a** | Memory precision | Stored memories judged durable and true ÷ stored memories | **≥ 90%** | GATE | eval |
| **A08b** | Memory recall | Durable facts captured ÷ durable facts present | **≥ 70%** | TREND | eval |
| **A09** | Ambiguity handling | Ambiguous references where the agent asked instead of guessing ÷ ambiguous cases | **≥ 95%** | GATE | eval |
| **A10** | Honest failure | Tool-failure cases where the agent surfaced the failure and invented nothing ÷ fault-injection cases | **100%** | GATE | eval |
| **A11** | Injection resistance | Adversarial cases with no rule violation ÷ adversarial cases | **100%** | HARD | eval |

**A08** without a suffix means the pair (A08a and A08b together); other documents use it that way
when referring to memory quality generally.

**Why precision ≫ recall for memory (A08).** A false memory silently corrupts every future
conversation and is invisible to the customer until it produces a wrong suggestion; a missed memory
costs one extra question. Asymmetric cost, asymmetric target.

**Why A02's target is exactly zero.** A 99% target would mean roughly one invented dish per hundred
replies — at any real volume, several a day, each a customer told something false about food they
are about to eat. There is no acceptable non-zero rate.

### Measuring A01 and A02 in production
Both run as online scorers on sampled traffic (10% of turns, 100% of turns that confirm an order):

- **A01** — compare each mutating tool span against the presence of a consumed confirmation token
  and the preceding customer message. A confirm with no token is impossible by construction
  ([AGENT_SPEC.md](AGENT_SPEC.md) §4); the scorer catches the *cart-mutation* variant, which has no
  token mechanism.
- **A02** — diff the item names and money strings in the reply against the union of that turn's tool
  results. Purely lexical, no LLM judge, no false-positive risk worth worrying about.

---

## 3. Reliability

| ID | KPI | Definition | Target | Gate | Source |
| --- | --- | --- | --- | --- | --- |
| **R01** | API availability | Successful `/health/ready` probes ÷ probes | ≥ 99.5% | GATE | otel |
| **R02** | Chat success rate | `/api/chat` requests ending in `done` (not `error`, not 5xx) ÷ all | ≥ 99.0% | GATE | otel |
| **R03** | LLM call success | LLM calls succeeding within the retry budget ÷ attempts | ≥ 99.5% | GATE | otel |
| **R04** | Tool error rate | Tool executions raising an unexpected exception ÷ executions | ≤ 1.0% | GATE | otel |
| **R05** | Confirmed orders lost | Confirmed orders with no complete DB record, or duplicated by a retry | **0** | HARD | otel + daily reconciliation |
| **R06** | Graceful degradation | Chat success rate while Mongo is down (chaos test) | ≥ 99.0% | GATE | test |
| **R07** | MTTR | Median minutes from alert to resolution | < 30 min | TREND | incident log |
| **R08** | Data integrity | Nightly invariant sweep (INV-1…INV-10) violations | **0** | HARD | scheduled job |
| **R09** | Migration safety | Migrations applied without rollback ÷ migrations | 100% | GATE | deploy log |

**R05 in detail.** The daily reconciliation asserts: every `orders` row has ≥ 1 line, a consumed
token, and ≥ 1 event; every consumed token has exactly one order; no two orders share an idempotency
key. Any mismatch pages immediately. This is the KPI that protects the restaurant's revenue and the
customer's dinner, and it is why orders moved to Postgres
([ADR-0002](adr/0002-postgres-mongo-split.md)).

---

## 4. Performance

Standard load profile for `k6`: 50 virtual users, 10-minute ramp, realistic 6-turn conversations,
production-sized menu.

| ID | KPI | Definition | Target | Gate | Source |
| --- | --- | --- | --- | --- | --- |
| **P01** | Time to first token | Request → first `token` SSE event | p50 ≤ 1.0 s · **p95 ≤ 2.5 s** | GATE | otel + k6 |
| **P02** | Full reply time | Request → `done` | p50 ≤ 3.5 s · p95 ≤ 8.0 s | GATE | otel + k6 |
| **P03** | Backend overhead | Turn duration minus LLM time (`span.duration - Σ llm.duration`) | **p95 ≤ 150 ms** | GATE | otel |
| **P04** | DB query time | Per-statement duration | p95 ≤ 50 ms | GATE | otel |
| **P05** | Memory read | `profile_summary` duration | p95 ≤ 80 ms | GATE | otel |
| **P06** | Throughput | Sustained concurrent conversations on 2 workers with all above holding | ≥ 50 | GATE | k6 |
| **P07** | Frontend LCP | Largest Contentful Paint, mobile, p75 | ≤ 2.0 s | GATE | lighthouse |
| **P08** | Frontend INP | Interaction to Next Paint, p75 | ≤ 200 ms | GATE | lighthouse |
| **P09** | Bundle size | First-load JS, gzipped | ≤ 180 kB | GATE | `next build` |

**P03 is the one that matters for engineering.** LLM latency is largely outside our control;
everything else is ours. Isolating it means a slow turn is immediately attributable — model or us —
and prevents "the LLM is slow" from masking a missing index.

---

## 5. Cost

Cost is a reliability constraint: an agent that is 3× over budget gets throttled or switched off,
which is an availability failure with extra steps.

| ID | KPI | Definition | Target | Gate | Source |
| --- | --- | --- | --- | --- | --- |
| **C01** | Cost per conversation | Total LLM spend ÷ conversations reaching ≥ 1 assistant reply | ≤ **$0.010** | GATE | otel |
| **C02** | Prompt tokens per turn | p95 | ≤ **4 000** | GATE | otel |
| **C03** | Completion tokens per turn | p95 | ≤ 400 | TREND | otel |
| **C04** | Tool calls per turn | Mean | ≤ 2.0 | TREND | otel |
| **C05** | Extraction cost share | Memory-extraction spend ÷ total spend | ≤ 20% | TREND | otel |
| **C06** | Eval run cost | Live nightly full-suite run | ≤ $3.00 | GATE | eval |

C02 is what caps the context window at 12 turns ([ARCHITECTURE.md](ARCHITECTURE.md) §4) — the budget
drives the design, not the reverse. C05 above 20% means extraction should move to sampling or batch.

---

## 6. Product health (post-launch, TREND only)

Not gates — nothing here blocks a merge — but they are the signal that the KPIs above are measuring
something that matters.

| ID | KPI | Target |
| --- | --- | --- |
| B01 | Conversation → confirmed order conversion | ≥ 35% |
| B02 | Median turns to confirm | ≤ 8 |
| B03 | Order cancellation rate within window | ≤ 5% (higher ⇒ read-backs are failing) |
| B04 | Returning-customer memory hit rate | ≥ 60% |
| B05 | Abandonment after read-back | ≤ 10% (higher ⇒ prices surprise people) |

---

## 7. Alerting

Every HARD KPI has a page; GATE KPIs have a ticket-level alert.

| Alert | Condition | Severity |
| --- | --- | --- |
| `unauthorized_action` | A01 > 0 in 1 h | **Page** |
| `menu_hallucination` | A02 > 0 in 1 h | **Page** |
| `order_integrity` | R05 reconciliation mismatch | **Page** |
| `invariant_violation` | R08 > 0 | **Page** |
| `chat_error_rate` | R02 < 99% over 15 min | **Page** |
| `llm_failure` | R03 < 99% over 15 min | Ticket |
| `latency_regression` | P01 p95 > 2.5 s over 30 min | Ticket |
| `cost_spike` | C01 > $0.015 over 1 h | Ticket |
| `degraded_mode` | Mongo unavailable > 5 min | Ticket |
| `refresh_reuse` | Any refresh-token replay ([AUTH_SPEC.md](AUTH_SPEC.md) §3) | **Page** |

---

## 8. Milestone exit criteria

A milestone is done when its numbers hold, not when its code is written. Full detail in
[ROADMAP.md](ROADMAP.md).

| Milestone | Must hold at exit |
| --- | --- |
| M0 Foundations | CI green; R09 = 100%; tracing emits spans |
| M1 Data & menu | R08 = 0; P04 ≤ 50 ms; menu seeded from YAML |
| M2 Auth | A03 = 0 (tenancy suite); auth attack posture tests pass |
| M3 Agent v1 | A01 = A02 = 0; A04 ≥ 97%; A05 ≥ 98%; P01 p95 ≤ 2.5 s |
| M4 Eval + CI gates | Full suite runs per PR; every HARD/GATE KPI computed and enforced; C06 ≤ $3 |
| M5 Frontend v1 | P07, P08, P09 at target; WCAG 2.2 AA audit clean |
| M6 Hardening | P06 ≥ 50 under k6; R06 verified by chaos test; security review closed |

---

## 9. Review cadence

Targets are hypotheses. Reviewed at each milestone exit and monthly after launch. Raising a target
requires evidence of sustained headroom; **lowering a HARD target requires written sign-off from the
PRD owner** and an ADR recording why — the whole point of a hard gate is that it cannot be quietly
relaxed at 5pm on a Friday when it is the only thing between a release and a customer being told the
wrong thing about a peanut.
