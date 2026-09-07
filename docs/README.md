# Documentation index

Specs for the Restaurant Ordering Agent. Read in this order — later documents assume earlier ones.

| # | Document | What it settles |
| --- | --- | --- |
| 1 | [PRD.md](PRD.md) | Scope, personas, 31 user stories with machine-checkable acceptance criteria, mobile requirements, the behavioural contract. ✅ **Signed off** |
| 2 | [DOMAIN_MODEL.md](DOMAIN_MODEL.md) | Entities, order lifecycle, confirmation protocol, money rules, 10 invariants. Technology-free |
| 3 | [ARCHITECTURE.md](ARCHITECTURE.md) | Component shape, anatomy of a turn, context assembly, failure matrix |
| 4 | [DATA_MODEL.md](DATA_MODEL.md) | Postgres DDL, Mongo documents, indexes, retention, migrations |
| 5 | [AGENT_SPEC.md](AGENT_SPEC.md) | System prompt v1.0.0, nine tools with JSON schemas, confirmation protocol, memory policy, residual risks |
| 6 | [API_CONTRACT.md](API_CONTRACT.md) | Every endpoint, the SSE event contract, error taxonomy, idempotency, rate limits |
| 7 | [AUTH_SPEC.md](AUTH_SPEC.md) | Accounts, JWT + rotating refresh, OAuth, the one authorization rule |
| 8 | [FRONTEND_SPEC.md](FRONTEND_SPEC.md) | Routes, components, streaming UX, accessibility, performance budget |
| 9 | [KPIS.md](KPIS.md) | **The measurement contract** — accuracy, reliability, performance, cost, with targets and gate classes. ✅ **Signed off** |
| 10 | [EVAL_PLAN.md](EVAL_PLAN.md) | Golden dataset, scorers, adversarial cases, CI gating, traceability matrix |
| 11 | [TEST_STRATEGY.md](TEST_STRATEGY.md) | Test pyramid, invariant tests, chaos, security sweep, CI pipeline |
| 12 | [OBSERVABILITY.md](OBSERVABILITY.md) | Spans, metrics, dashboards, alerts, PII policy |
| 13 | [ROADMAP.md](ROADMAP.md) | M0–M6 with KPI-gated exit criteria, risks |
| 14 | [RUNBOOK.md](RUNBOOK.md) | Local setup, deploy, incident response, alert playbooks |

**Decisions:** [adr/](adr/) — [0001 Agents SDK + DeepSeek](adr/0001-agents-sdk-deepseek.md) ·
[0002 Postgres/Mongo split](adr/0002-postgres-mongo-split.md) ·
[0003 SSE over WebSocket](adr/0003-sse-over-websocket.md) ·
[0004 Confirmation in code](adr/0004-confirmation-in-code.md) ·
[0005 Email+password only](adr/0005-email-password-only-v1.md) ·
[0006 LLM latency / model switch](adr/0006-llm-latency-finding.md) ·
[0007 Tolerant tool arguments](adr/0007-tolerant-tool-arguments.md)

**Conventions for contributors:** [../CLAUDE.md](../CLAUDE.md)

---

## The short version

An ordering agent is only useful if it is trustworthy, so four properties are enforced structurally
rather than asked for in a prompt:

1. **No order without a server-issued confirmation token** the model never sees
   ([ADR-0004](adr/0004-confirmation-in-code.md)).
2. **No `user_id` parameter on any tool** — identity comes from the verified session, so the model
   cannot express the concept of another customer.
3. **No self-computed totals** — money comes from tool output and is echoed verbatim.
4. **No unbounded context** — 12 turns, 4 000 tokens, so cost and latency cannot drift with
   conversation length.

Everything else — the eval harness, the KPI gates, the observability spec — exists to prove those
four hold, and to catch it the same day if they stop.

## Reading paths

**Implementing a feature:** DOMAIN_MODEL → the relevant spec → EVAL_PLAN §2 for the case format.
**Reviewing a PR:** CLAUDE.md non-negotiables → the eval scorecard on the PR.
**On call:** RUNBOOK §6 → OBSERVABILITY §5.
**Deciding whether to ship:** KPIS §8 → ROADMAP exit criteria → PRD §8.

---

## Status

PRD and KPIS are **signed off** (2026-09-06) — M1 is unblocked. M0 comes first, and its opening task
is consolidating the nested git repos in `backend/` and `frontend/` into one at the root
([ROADMAP.md](ROADMAP.md) M0).
