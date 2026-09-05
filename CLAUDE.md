# Restaurant Ordering Agent — working conventions

Conversational ordering agent. Next.js frontend, FastAPI backend, OpenAI Agents SDK on DeepSeek,
Postgres for state, MongoDB for long-term memory.

**Read before changing behaviour:** [docs/AGENT_SPEC.md](docs/AGENT_SPEC.md) ·
[docs/DOMAIN_MODEL.md](docs/DOMAIN_MODEL.md) · [docs/KPIS.md](docs/KPIS.md)

---

## Non-negotiables

These are hard gates in [docs/KPIS.md](docs/KPIS.md). A single violation blocks merge.

1. **The agent never invents menu data.** Items, prices, and availability come from tool results
   only (A02).
2. **No order without a consumed confirmation token.** `confirm_order` takes no token parameter —
   see [ADR-0004](docs/adr/0004-confirmation-in-code.md). Do not add one (A01).
3. **`user_id` never comes from the model or the request body.** It comes from the verified session
   through `RunContextWrapper[ChatContext]` (A03).
4. **Money is integer minor units.** No floats in Python, SQL, or API payloads. Formatting happens
   at the display boundary only.
5. **A foreign resource returns `NOT_FOUND`, never `FORBIDDEN`.** A 403 confirms existence.

---

## Where things go

```
backend/app/
  api/          routes: validate, resolve session, call services. No business rules
  agent/        prompt, model config, tools (thin adapters)
  services/     ALL business rules and transactions. Testable without FastAPI or an LLM
  db/           repositories and connections. No business rules
frontend/src/
  app/          routes (Server Components by default)
  components/   "use client" only where interaction requires it
  lib/api.ts    the only place that talks to the backend
docs/           specs — the source of truth for intended behaviour
evals/          golden dataset, scorers, gate
```

Dependencies point downward. A service must never import from `api/` or `agent/`.

---

## Conventions

**Python** — 3.12+, `async def` throughout, full type hints (`mypy --strict` on `app/`), `ruff`
format and lint. Pydantic models for every boundary. Every service method takes `user_id` as its
first argument.

**TypeScript** — strict mode, no `any`. API types are **generated** from OpenAPI — do not hand-edit
`src/lib/api.ts` types. Tailwind utilities; no component library.

**SQL** — Alembic for every schema change, with a working `downgrade`. Expand/contract for
destructive changes. Never `create_all`.

**Naming** — tools are verb-first and unambiguous (`update_cart_item`, not `cart`). Error codes are
`SCREAMING_SNAKE` and stable; clients branch on the code, never the message.

---

## Before you commit

```bash
cd backend  && uv run ruff check . && uv run mypy app && uv run pytest tests/unit
cd frontend && npm run lint && npx tsc --noEmit && npm run build
```

Touching the agent prompt or tools additionally requires:

```bash
uv run python -m evals.run --mode recorded      # every PR
uv run python -m evals.run --mode live --repeats 3   # prompt changes only
```

A prompt change is a **version bump** in `app/agent/prompts/` plus a scorecard diff on the PR.
Recorded-mode results are meaningless for a prompt change — the cassettes predate it.

---

## Changing behaviour

1. Update the spec in `docs/` **first**. The docs are the contract; code that disagrees with them is
   the thing that is wrong.
2. Add or update the eval case ([docs/EVAL_PLAN.md](docs/EVAL_PLAN.md)) or test.
3. Implement.
4. Verify the traceability matrix still has no orphans: `uv run python -m evals.trace_matrix`.

Every production bug becomes an eval case or a test **before** its fix merges.

---

## Watch out for

- `backend/app/agent/menu.py` is scaffold-era hardcoded data; it is replaced by
  `backend/seeds/menu.yaml` in M1 and then deleted.
- `Base.metadata.create_all` in `app/db/postgres.py` is dev-only and gets removed when Alembic lands.
  If you see it in production code, that is a bug.
- `ChatRequest.user_id` in `app/api/chat.py` accepts identity from the request body. Scaffold-only,
  removed in M2 — never build on it.
- `useUserId` in `frontend/src/components/Chat.tsx` invents a localStorage id. Deleted in M2.
- Memory extraction failures are swallowed by design. Never let a memory bug break a chat.
- MongoDB being down is **degraded, not broken** — chat must still work
  ([docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) §6).

---

## Current state

Scaffold only: chat round-trip, three tools, hardcoded menu, no auth, no tests, no evals. The specs
in `docs/` describe the target. [docs/ROADMAP.md](docs/ROADMAP.md) sequences the work — M0 first, and
its first task is consolidating the nested git repos in `backend/` and `frontend/` into one at the
root.
