# Test Strategy

**Version:** 1.0.0 · Covers everything the eval suite does not.

The eval suite ([EVAL_PLAN.md](EVAL_PLAN.md)) proves the *agent* behaves. This document proves the
*system* behaves — and most of the safety guarantees live in the system, not the agent.

---

## 1. Shape

```
        /\        e2e (Playwright)          ~12   minutes
       /  \       eval (golden set)        ~120   90 s, recorded
      /----\      contract (OpenAPI ↔ TS)    ~3   seconds
     /      \     integration (real DBs)    ~90   3 min
    /--------\    unit (pure logic)        ~250   10 s
   /__________\   load (k6) + chaos          ~6   on demand
```

Deliberately unusual proportions: the integration tier is heavy because nearly every invariant in
this system is a *transaction* property, and a mocked database proves nothing about a transaction.

**Speed budget:** unit + contract < 15 s (pre-commit); + integration < 4 min (per push); + eval
< 6 min (per PR); e2e + load nightly.

---

## 2. Rules

1. **No mocked database in the integration tier.** Testcontainers Postgres and Mongo. A mocked
   `SELECT … FOR UPDATE` cannot fail the way a real one does.
2. **The LLM is always faked below the eval tier.** Deterministic, free, fast.
3. **Deterministic time and ids.** A frozen clock and seeded id generator — the 10-minute
   cancellation window (Rule L2) and the 5-minute token TTL are untestable otherwise.
4. **One assertion subject per test.** A test named `test_confirm_is_atomic` asserts atomicity.
5. **Every bug gets a failing test first.** Non-negotiable; it is what stops regressions recurring.

---

## 3. Unit tier — pure logic, no I/O

Targets the code where an error is silent and expensive.

| Area | Cases |
| --- | --- |
| **Money** (Rules $1–$6) | Integer arithmetic; tax rounds half-up once on the subtotal, not per line; negative `price_delta`; large quantities; no float anywhere in the path |
| **Cart rules** | C1 merge on identical item+options; separate lines on differing options; C2 bounds (0 removes, 21 rejects); C3 unavailable rejected |
| **Order state machine** | Every legal transition in [DOMAIN_MODEL.md](DOMAIN_MODEL.md) §2 succeeds; every illegal one raises (table-driven over all 36 pairs); terminal states are terminal |
| **Cancellation window** | 9:59 allowed, 10:01 refused, exactly 10:00 refused (boundary stated explicitly so it is never ambiguous); `preparing` refused regardless of time |
| **Confirmation tokens** | Valid consumes; expired refused; reused refused; stale `cart_version` refused; another user's token refused |
| **Memory policy** | Durability (N1); deny-list (N2, INV-10); allergy supremacy (N3); dedupe; confidence floor 0.8 |
| **Context assembly** | 12-turn window; 4 000-token budget; history truncates oldest-first; prompt and memory blocks never truncated |
| **Auth rule** | An active account must have a password or ≥ 1 OAuth link (the rule [DATA_MODEL.md](DATA_MODEL.md) §2.1 deliberately does not express in DDL) |

Coverage gate: **≥ 90%** on `app/services/`, **≥ 85%** on `app/agent/` and `app/api/`.

---

## 4. Integration tier — real databases

| Area | Cases |
| --- | --- |
| **Invariants INV-1…INV-10** | One test each; the DDL constraint or service rule from [DATA_MODEL.md](DATA_MODEL.md) §8 is exercised against a live DB |
| **Confirm atomicity (R1, INV-8)** | Inject a failure after the order insert but before the cart clear → nothing persists, token unconsumed. Kill the connection mid-transaction → same |
| **Idempotency (R05)** | Same key twice → one order, identical response. Same key, different body → `409`. Concurrent duplicate confirms → exactly one order |
| **Concurrency** | Two simultaneous `add_to_cart` for the same item → one merged line with the right quantity (row lock holds). Confirm racing a cart edit → one wins, the other gets `CART_CHANGED` |
| **One open cart (INV-3)** | Concurrent cart creation → unique index rejects the second |
| **Tenancy** | See §7 |
| **Migrations** | `alembic upgrade head` on empty; every `downgrade` runs; `alembic check` finds no model drift |
| **Cross-store deletion** | `delete-user` clears Postgres rows and the Mongo profile; orders anonymised, not deleted (retention policy) |
| **Degradation** | Mongo unavailable → chat returns 200 with an empty memory block; Postgres unavailable → `503 STORAGE_UNAVAILABLE` |

---

## 5. Contract tier

- **OpenAPI ↔ TypeScript.** Types for `frontend/src/lib/api.ts` are generated from `/openapi.json`;
  CI regenerates and fails on a diff. Prevents the classic silent break where the backend renames a
  field and the frontend renders `undefined`.
- **Tool schemas.** Every tool in [AGENT_SPEC.md](AGENT_SPEC.md) §5 is asserted to be valid JSON
  Schema with `additionalProperties: false`, and to match the registered Python signature — the
  scaffold already exposes this via `tool.params_json_schema`.
- **SSE events.** Every event type in [API_CONTRACT.md](API_CONTRACT.md) §4 validates against its
  schema; unknown types are proven non-fatal for the client.

---

## 6. Chaos / fault injection

Runs nightly against staging; backs R03, R04, R06 and eval family `FAIL`.

| Fault | Expected |
| --- | --- |
| Mongo killed mid-conversation | Chat continues; `degraded.memory` set; R02 holds ≥ 99% (**R06**) |
| Postgres connection killed mid-turn | `503`; no partial write; recovery on reconnect |
| LLM returns 500 twice then 200 | One coherent reply; retry visible in the trace |
| LLM hangs past timeout | Timeout at 20 s; honest error; no zombie stream |
| LLM emits a malformed tool call | Handled; no crash; no invention |
| Network partition mid-confirm | Client retries with the same idempotency key → exactly one order (**R05**) |
| Clock skew on token expiry | Server time authoritative; no early acceptance |

---

## 7. Security tests

`tests/security/` — these back hard gate A03 and the posture in [AUTH_SPEC.md](AUTH_SPEC.md) §7.

- **Tenancy sweep** (the important one): create users A and B; from B's session, attempt **every**
  route and **every** tool against A's cart, orders, conversations, memories, and profile. Assert
  `NOT_FOUND` (never `FORBIDDEN`) and assert none of A's field values appear anywhere in the
  response body. Parameterised over all endpoints so a new route without an owner filter fails
  automatically.
- Auth: refresh rotation, reuse detection revokes the family, reset revokes all sessions, no
  enumeration oracle on login/forgot (response *and* timing), CSRF double-submit enforced,
  expired/tampered/`alg=none` JWTs rejected.
- Injection: SQL injection through every free-text field (item notes, memory text, display name);
  XSS payloads in model output rendered inert by the frontend.
- Secrets: no secret in logs, in error bodies, or in the frontend bundle (grep gate in CI).

---

## 8. End-to-end

Playwright, staging, real browser, faked LLM at the boundary for determinism.

| Flow | Assertion |
| --- | --- |
| Register → chat → order | Order appears in the DB and in the UI with the right total |
| Login → memory recall | A stored preference visibly shapes the next conversation |
| Read-back → edit → re-confirm | Stale confirmation cannot be used (US-15) |
| Cancel in window | Status becomes `cancelled`; UI reflects it |
| Streaming | Tokens render progressively; tool affordance appears; `done` closes cleanly |
| Network drop mid-stream | Reconnect or a clean error; never a half-rendered reply |
| Keyboard-only order | Full path without a mouse (WCAG) |
| `mobile-order-flow` | Full order path at 375 × 667 **and** 320 px; no horizontal scroll on any screen (US-28) |
| `mobile-cart-visibility` | Total bar in viewport whenever the cart is non-empty; confirm dialog fully readable, scrollable not clipped (US-29) |
| `mobile-keyboard` | Composer stays above a simulated keyboard inset; latest message scrolled into view after send; CLS ≤ 0.1 on open/close (US-30) |
| Breakpoint sweep | 320 / 375 / 768 / 1024 / 1440 px × light and dark: no overflow, no clipped controls, targets ≥ 44 px |
| Orientation change | Composer content and cart state survive portrait ↔ landscape |

---

## 9. Load

`k6`, the standard profile from [KPIS.md](KPIS.md) §4: 50 VUs, 10-min ramp, 6-turn conversations,
production-sized menu, LLM stubbed at a realistic latency distribution (p50 900 ms, p95 2.2 s) so the
test measures **our** overhead (P03), not DeepSeek's.

Gates P01–P06. Run nightly on staging and before every release; a release is blocked on a regression.

---

## 10. CI pipeline

| Stage | Runs | Blocks |
| --- | --- | --- |
| Lint + types (`ruff`, `mypy`, `tsc`, `eslint`) | every push | yes |
| Unit + contract | every push | yes |
| Integration | every PR | yes |
| Eval (recorded) | every PR | yes — per [EVAL_PLAN.md](EVAL_PLAN.md) §8 |
| Coverage gate | every PR | yes |
| Security tests | every PR | yes |
| Build (both apps) + bundle size | every PR | yes (P09) |
| e2e | merge to main | yes |
| Load + chaos + live eval | nightly | ticket, not block |
| Lighthouse | merge to main | yes (P07, P08) |

Required for merge: all "yes" rows green, plus review. No admin bypass on the eval and security
stages.

---

## 11. Test data

- **Fixtures are synthetic.** No production data in tests, ever.
- **One menu source.** `backend/seeds/menu.yaml` feeds dev, tests, and evals — a divergent test menu
  produces evals that pass against a menu no customer ever sees.
- **Named personas** matching [PRD.md](PRD.md) §4: `nadia` (new, empty profile), `raj` (returning,
  vegetarian, peanut allergy, order history), `mallory` (adversarial). Reused across every tier so a
  failure reads as a story rather than a uuid.
