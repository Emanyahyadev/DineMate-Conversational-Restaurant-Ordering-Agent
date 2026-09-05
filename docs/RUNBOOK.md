# Runbook

**Version:** 1.0.0 · Operating the Restaurant Ordering Agent.

---

## 1. Local setup

Prerequisites: Docker, `uv`, Node 20+.

```bash
git clone <repo> && cd "Restaurant ordering agent"
docker compose up -d                 # Postgres, Mongo, OTLP collector

cd backend
cp .env.example .env                 # fill DEEPSEEK_API_KEY and JWT_SECRET
uv sync
uv run alembic upgrade head
uv run python -m app.cli seed-menu
uv run fastapi dev app/main.py       # http://localhost:8000

cd ../frontend
cp .env.example .env.local
npm install
npm run dev                          # http://localhost:3000
```

Verify: `curl localhost:8000/health/ready` → `{"status":"ok"}`, and `/api/menu` returns items.

**A note for the current state of the repo:** until M1 lands there is no Alembic and no seed CLI —
the app creates tables on startup and the menu is `backend/app/agent/menu.py`. Skip those two lines
and the rest works.

---

## 2. Environment variables

| Variable | Required | Notes |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | prod, dev | Chat fails without it; `/health` and `/api/menu` still work |
| `DEEPSEEK_BASE_URL` | | Default `https://api.deepseek.com/v1` |
| `LLM_MODEL` | | Default `deepseek-chat` |
| `POSTGRES_URL` | **yes** | `postgresql+asyncpg://…`. App is unusable without it |
| `MONGODB_URL` | | Absent ⇒ degraded mode, not failure |
| `JWT_SECRET` | **yes (prod)** | ≥ 32 bytes; boot refuses on a dev default |
| `GOOGLE_OAUTH_CLIENT_ID/SECRET` | for OAuth | |
| `CORS_ORIGINS` | **yes** | JSON array. Never `["*"]` |
| `TAX_RATE` | | Decimal, e.g. `0.08` |
| `CANCELLATION_WINDOW_MINUTES` | | Default 10 (Rule L2) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | prod | |
| `OTEL_ENABLED` | | `false` for fast local tests |

Secrets come from the platform's secret manager in staging and production — never from a file in the
repo. Rotation: §7.

---

## 3. Common tasks

```bash
# Migrations
uv run alembic revision --autogenerate -m "add option groups"
uv run alembic upgrade head
uv run alembic downgrade -1                 # every migration must support this

# Menu
uv run python -m app.cli seed-menu          # from backend/seeds/menu.yaml
uv run python -m app.cli set-availability m7 false    # 86 an item

# Orders (v1 ops stand-in for a kitchen display)
curl -X POST localhost:8000/internal/orders/ORD-482910/status \
  -H "X-Internal-Secret: $INTERNAL_SECRET" -d '{"to_status":"preparing","actor":"staff"}'

# Evals
uv run python -m evals.run --mode recorded
uv run python -m evals.run --mode live --repeats 3 --record
uv run python -m evals.trace_matrix

# Tests
uv run pytest tests/unit -q
uv run pytest tests/integration            # needs Docker
uv run pytest tests/security

# Privacy
uv run python -m app.cli delete-user <user_id>       # spans both stores
```

---

## 4. Deploy

Backend and frontend deploy independently; the API is additive-only within v1
([API_CONTRACT.md](API_CONTRACT.md) §11), so ordering does not matter for compatible changes.

1. CI green on main (unit, integration, eval, security, e2e).
2. **Migrations first**, before the new code: `alembic upgrade head` against production.
   Expand/contract means a migration is always compatible with the *currently running* code.
3. Deploy backend; watch `/health/ready` and the error rate for 10 minutes.
4. Deploy frontend.
5. Smoke: register a throwaway account, order, check status, cancel.

**Rollback.** Code: redeploy the previous image. Schema: **do not** auto-downgrade in production —
expand/contract means the old code runs against the new schema, so roll back code only, then decide
about the schema deliberately.

---

## 5. Incident response

1. **Acknowledge** the page.
2. **Assess** — is it customer-visible? Are orders affected?
3. **Communicate** — if orders are affected, tell the restaurant immediately. They can take phone
   orders; they cannot recover the ones they never knew about.
4. **Mitigate before diagnosing.** Roll back, disable, degrade.
5. **Diagnose** from traces: find `X-Request-Id` → the trace → the span tree.
6. **Write it up** within 48 h, blameless, and **add an eval case or test** for the failure — that
   step is what makes the postmortem worth writing.

**Severity.** Sev1 = orders lost/wrong, data leaked, chat down > 5 min → page, restaurant informed.
Sev2 = degraded, elevated errors, latency breach → page in hours. Sev3 = cosmetic, single-user →
ticket.

---

## 6. Alert playbooks

Every page in [KPIS.md](KPIS.md) §7 has an entry here. First action, then diagnosis.

### `unauthorized_action` (A01 > 0) — **Sev1**
An order or cart mutation happened without consent. *This is supposed to be structurally impossible.*
1. Find the trace; check `confirmation.token_consumed` on the span.
2. If `false` on a `confirm_order` — the token check has been bypassed or removed. **Disable
   `confirm_order` via feature flag immediately** and take orders by phone.
3. If a cart mutation — lower severity; capture the conversation as an eval case.
4. Always: add the case to the golden set before the fix merges.

### `menu_hallucination` (A02 > 0) — **Sev1**
Customers are being told false things about food.
1. Trace → what was said versus tool results. Check the item's allergen fields.
2. If allergen-related, treat as a safety incident: inform the restaurant, consider disabling
   dietary recommendations via flag.
3. Check whether the prompt version changed recently → roll back the prompt.

### `order_integrity` (R05) — **Sev1**
1. Run the reconciliation query manually; identify affected order ids.
2. **Contact the restaurant with the list** — a missing order is someone's dinner.
3. Check for duplicate idempotency keys and orphaned tokens.
4. Do not "fix" rows by hand until the cause is understood; write the finding down first.

### `chat_error_rate` (R02 < 99%)
Check `/health/ready` first — Postgres, Mongo, LLM. Postgres → §6.5. LLM → check the provider status
and `llm.calls{outcome="error"}` by `attempt`; if the provider is down, switch `LLM_MODEL` to the
fallback and announce degraded service.

### `latency_regression` (P01 p95 > 2.5 s)
Look at the **overhead vs. LLM time** panel first. If overhead grew, it is ours — check `db.query`
p95 for a missing index and `context.assemble` for prompt growth (C02). If LLM time grew, it is the
provider — consider the fallback model, and set expectations in the UI rather than pretending.

### `cost_spike` (C01 > $0.015)
Check C02 (prompt tokens) — runaway context is the usual cause, often a truncation bug. Then C04
(tool calls per turn) for a loop, and C05 for extraction running away.

### `degraded_mode` (Mongo down)
Expected behaviour, not an outage: chat works without personalisation. Confirm R02 is still ≥ 99%,
restore Mongo, verify memory reads resume. **Do not** fail the service over this.

### `refresh_reuse`
A refresh token was replayed — assume theft. The family is already revoked automatically. Check
whether one user or many; if many, treat as a platform compromise and rotate `JWT_SECRET` (§7).

---

## 7. Secret rotation

**`JWT_SECRET`:** deploy with both old and new keys accepted (`kid` header), sign with the new,
wait for the access-token TTL (15 min) plus a margin, then drop the old. Users stay signed in.
Emergency (compromise): rotate immediately without the overlap — every session is invalidated and
everyone re-logs-in. Correct, and preferable to leaving forged tokens valid.

**`DEEPSEEK_API_KEY`:** provision the new key, update the secret, restart. No user impact.

**Database credentials:** Neon/Atlas rolling credential change, then restart. Brief connection
errors are expected; the app retries.

---

## 8. Backups

| Data | Backup | Restore target |
| --- | --- | --- |
| Postgres | Neon PITR, 7-day window | < 1 h |
| Mongo | Atlas daily snapshot | < 4 h (memory is regenerable — degraded, not lost) |
| Traces/metrics | Not backed up | — |

**Restore drill quarterly.** An untested backup is a hypothesis. The drill restores to a scratch
environment and verifies the invariant sweep (R08) passes against the restored data.

---

## 9. On-call expectations

Sev1: acknowledge 15 min, mitigate 60 min, restaurant informed if orders are affected. Sev2:
acknowledge 1 h. Sev3: next business day.

Escalate when: the cause is not clear within 30 minutes, customer data may have been exposed, or the
mitigation itself carries risk. Escalating early is never the wrong call.
