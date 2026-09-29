# API Contract

**Base:** `/api` · **Version:** 1.0.0 · **Auth:** JWT in httpOnly cookies
([AUTH_SPEC.md](AUTH_SPEC.md))

The OpenAPI document FastAPI generates at `/openapi.json` is the machine-readable form of this file;
the frontend's `src/lib/api.ts` types are generated from it, and CI fails if they drift
([TEST_STRATEGY.md](TEST_STRATEGY.md) §5).

---

## 1. Conventions

- JSON in, JSON out; UTF-8; `Content-Type: application/json`.
- **Money is always two fields**: `*_cents` (integer, authoritative) and `*_display` (string,
  preformatted `"$9.50"`). Clients render `display` and compute with `cents`. Never a float
  (Rule $1).
- Timestamps are RFC 3339 UTC (`2026-09-06T14:22:31Z`).
- Ids: users/carts/conversations are UUID strings; orders are `ORD-` + 6 digits.
- Unknown request fields are rejected (`additionalProperties: false`) — a silently ignored typo is a
  bug waiting to ship.
- Every response carries `X-Request-Id`, which equals the OTel trace id
  ([OBSERVABILITY.md](OBSERVABILITY.md) §2).

---

## 2. Errors

One shape everywhere:

```json
{ "error": { "code": "CART_CHANGED",
             "message": "Your cart changed since we reviewed it.",
             "details": { "cart_version": 8 },
             "request_id": "b7f2…" } }
```

`code` is stable and machine-readable — clients and eval scorers branch on it, never on `message`.
`message` is customer-safe: it never leaks internals, ids belonging to others, or stack traces.

| Code | HTTP | Meaning |
| --- | --- | --- |
| `VALIDATION_ERROR` | 400 | Malformed body; `details` names the fields |
| `UNAUTHENTICATED` | 401 | Missing or expired access token |
| `FORBIDDEN` | 403 | Authenticated but not the owner |
| `NOT_FOUND` | 404 | Resource absent **or** not owned (deliberately indistinguishable — US-18) |
| `CONFLICT` | 409 | Idempotency key reused with a different body |
| `CART_CHANGED` | 409 | Confirmation token stale (§4 of the agent spec) |
| `NO_CONFIRMATION` | 409 | Confirm attempted without a valid token |
| `CART_EMPTY` | 409 | Nothing to confirm |
| `ITEM_UNAVAILABLE` | 409 | 86'd item in the cart at confirm time |
| `CANCELLATION_WINDOW_EXPIRED` | 409 | Past the 10-minute window (Rule L2) |
| `ORDER_NOT_CANCELLABLE` | 409 | Status beyond `confirmed` (Rule L3) |
| `RATE_LIMITED` | 429 | `Retry-After` header set |
| `STORAGE_UNAVAILABLE` | 503 | Postgres down — hard fail ([ARCHITECTURE.md](ARCHITECTURE.md) §6) |
| `LLM_UNAVAILABLE` | 503 | Model unreachable after retries (non-streaming paths only) |
| `INTERNAL_ERROR` | 500 | Unexpected; `request_id` is the handle for support |

---

## 3. Auth endpoints

Full semantics in [AUTH_SPEC.md](AUTH_SPEC.md); the wire shapes:

| Method | Path | Body → Response |
| --- | --- | --- |
| POST | `/api/auth/register` | `{email, password, display_name?}` → `201 {user}` + cookies |
| POST | `/api/auth/login` | `{email, password}` → `200 {user}` + cookies |
| POST | `/api/auth/logout` | — → `204`, session revoked |
| POST | `/api/auth/refresh` | — (refresh cookie) → `200 {user}` + rotated cookies |
| GET | `/api/auth/me` | — → `200 {user}` |
| GET | `/api/auth/oauth/google` | → `302` to Google |
| GET | `/api/auth/oauth/google/callback` | → `302` to app + cookies |
| POST | `/api/auth/password/forgot` | `{email}` → `202` (always 202 — never reveals whether the account exists) |
| POST | `/api/auth/password/reset` | `{token, new_password}` → `204`, all sessions revoked |

`user` = `{ id, email, display_name, email_verified, created_at }`.

---

## 4. Chat (SSE)

### `POST /api/chat`

The only streaming endpoint. Replaces the request/response version in
`backend/app/api/chat.py`, which cannot meet KPI P01.

**Request** — omit `conversation_id` to start a new conversation.
```json
{ "message": "two margheritas and a lemonade",
  "conversation_id": "8f1c2d4e-0000-4000-8000-000000000001" }
```

**Response** — `200`, `Content-Type: text/event-stream`, `X-Accel-Buffering: no`.

| Event | Data | Purpose |
| --- | --- | --- |
| `start` | `{conversation_id, message_id, trace_id}` | Sent immediately — lets the client bind state before any token |
| `token` | `{delta: "Sure, "}` | Text delta |
| `tool` | `{name, phase: "start"\|"end", label: "Checking the menu…"}` | Drives the UI affordance |
| `cart` | `{cart}` (full snapshot) | Emitted after any mutation so the cart panel stays truthful without polling |
| `done` | `{message_id, usage:{prompt_tokens,completion_tokens,cost_cents}, duration_ms}` | Terminal, success |
| `error` | `{code, message}` | Terminal, failure — the stream still closes cleanly with HTTP 200 |

```
event: start
data: {"conversation_id":"8f1c…","message_id":9013,"trace_id":"b7f2…"}

event: tool
data: {"name":"search_menu","phase":"start","label":"Checking the menu…"}

event: token
data: {"delta":"Two Margheritas"}

event: done
data: {"message_id":9013,"usage":{"prompt_tokens":1840,"completion_tokens":96,"cost_cents":0.3},"duration_ms":2310}
```

**Contract notes.** `start` precedes everything, so TTFT (KPI P01) is measured from request to the
first `token`, not to `start`. An error *after* streaming began arrives as an `error` event, not an
HTTP status — the status is already sent. Clients must tolerate unknown event types (forward
compatibility). Heartbeat comment `:ping` every 15 s keeps proxies from closing idle streams.

### `GET /api/conversations`
`?limit=20&cursor=…` → `{ items: [{id, title, updated_at, last_message_preview}], next_cursor }`

### `GET /api/conversations/{id}`
→ `{ id, created_at, messages: [{id, role, content, created_at}] }`. Owner-filtered; a foreign id
returns `NOT_FOUND`.

### `DELETE /api/conversations/{id}` → `204`

---

## 5. Menu

### `GET /api/menu`
`?category=Pizza&dietary_tag=vegan&exclude_allergens=peanut,dairy&q=spicy`

```json
{ "items": [ { "id": "m1", "name": "Margherita Pizza", "description": "…",
    "category": "Pizza", "price_cents": 950, "price_display": "$9.50",
    "dietary_tags": ["vegetarian"], "allergens": ["gluten","dairy"],
    "allergens_verified": true, "is_available": true } ] }
```
Public (no auth). Only `is_active AND is_available` rows. Cached 60 s server-side; `Cache-Control:
public, max-age=60`.

### `GET /api/menu/full`
```json
{ "items": [ /* every offerable dish, same shape as above, uncapped */ ],
  "categories": ["Starters", "…"],
  "restaurants": [ { "id": "r1", "name": "…", "cuisine": "…", "item_count": 9,
    "categories": ["…"], "dietary_tags": ["…"],
    "rating": { "average": 4.6, "count": 12 } } ] }
```
Public (no auth), `Cache-Control: public, max-age=60`, served from the same 60 s cache as
`GET /api/menu`.

`GET /api/menu` caps its answer because it is sized for the agent's prompt budget; a human
browsing wants the whole board. This exists so that browse is **one** request rather than one per
restaurant plus two for the list — the caps are unchanged, and so is what the agent sees.

Declared before `/api/menu/{item_id}` so `full` is not read as an item id.

### `GET /api/menu/{item_id}`
Adds `option_groups: [{id, name, min_select, max_select, options:[{id,name,price_delta_cents,
price_delta_display}]}]`.

---

## 6. Cart

All require auth and operate on the caller's single open cart (INV-3). Every mutation returns the
**full cart**, so the client never reconstructs state from deltas.

```json
{ "cart": { "id": "…", "version": 7,
    "lines": [ { "line_id": "…", "item_id": "m1", "name": "Margherita Pizza",
                 "quantity": 2, "unit_price_cents": 950, "unit_price_display": "$9.50",
                 "line_total_cents": 1900, "line_total_display": "$19.00",
                 "options": [], "note": "" } ],
    "subtotal_cents": 2250, "subtotal_display": "$22.50",
    "tax_cents": 180, "tax_display": "$1.80",
    "total_cents": 2430, "total_display": "$24.30",
    "updated_at": "2026-09-06T14:22:31Z" } }
```

| Method | Path | Body | Notes |
| --- | --- | --- | --- |
| GET | `/api/cart` | — | Creates an empty cart if none open |
| POST | `/api/cart/lines` | `{item_id, quantity?, option_ids?, note?}` | Merges per Rule C1; bumps `version` |
| PATCH | `/api/cart/lines/{line_id}` | `{quantity}` | **Sets**, not increments; `0` removes |
| DELETE | `/api/cart/lines/{line_id}` | — | |
| DELETE | `/api/cart` | — | Empties |

Any mutation invalidates outstanding confirmation tokens (US-15).

---

## 7. Orders

### `POST /api/orders`
Header `Idempotency-Key: <uuid>` **required**.
```json
{ "confirmation_token": "…", "fulfilment": "pickup", "notes": "" }
```
→ `201 { "order": { "id": "ORD-482910", "status": "confirmed", "fulfilment": "pickup",
"lines": [...], "subtotal_cents": …, "tax_cents": …, "total_cents": …, "total_display": "$24.30",
"confirmed_at": "…", "cancellable_until": "…", "eta_minutes": 25 } }`

Errors: `NO_CONFIRMATION`, `CART_CHANGED`, `CART_EMPTY`, `ITEM_UNAVAILABLE`.

**Idempotency.** Same key + same body → the original `201` response, byte-identical, no second
order. Same key + different body → `409 CONFLICT`. Keys are retained 24 h. This is the mechanism
behind KPI R05: a retried confirm can never double-order.

**Note on the token.** The HTTP endpoint takes `confirmation_token` explicitly because the browser
UI is a legitimate second caller (the "Place order" button in
[FRONTEND_SPEC.md](FRONTEND_SPEC.md) §4). The *agent tool* `confirm_order` takes no token — it
reads it from server-side turn context so the model can never mint or replay one
([AGENT_SPEC.md](AGENT_SPEC.md) §4).

### `GET /api/orders` → `{ items: [order], next_cursor }`, owner-filtered, newest first
### `GET /api/orders/{id}` → `{ order }` (+ `events: [{from_status,to_status,actor,created_at}]`)
### `POST /api/orders/{id}/cancel` → `{ order }`
`{reason?}`; enforces Rules L2/L3. Errors: `CANCELLATION_WINDOW_EXPIRED`, `ORDER_NOT_CANCELLABLE`.

### `POST /internal/orders/{id}/status` *(v1 ops stand-in)*
`{to_status, actor:"staff"}`. Protected by a shared secret header, never exposed to the browser, not
in the public OpenAPI doc. Exists so status can advance without a KDS (PRD §3).

---

## 8. Profile and memory

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/profile` | `{ user, stats: {orders_placed, last_order_at} }` |
| GET | `/api/profile/memories` | `{ preferences: [{id,text,kind?,created_at}], facts: [...] }` — US-24 |
| DELETE | `/api/profile/memories/{memory_id}` | `204`; absent from the next turn's context |
| DELETE | `/api/profile` | `202`; queues the cross-store deletion job ([DATA_MODEL.md](DATA_MODEL.md) §6) |

---

## 9. Operational endpoints

| Path | Purpose |
| --- | --- |
| `GET /health` | Liveness. No dependency checks — already exists |
| `GET /health/ready` | Readiness: Postgres required; Mongo reported but **not** fatal (R06) |
| `GET /metrics` | Prometheus, internal only |

```json
{ "status": "degraded", "checks": { "postgres": "ok", "mongo": "unavailable", "llm": "ok" } }
```
`ready` returns 200 for `ok`/`degraded`, 503 only when Postgres is down — matching the failure
matrix exactly, so orchestration never removes a pod that is still able to serve chat.

---

## 10. Rate limits

Per user (authenticated) or per IP (anonymous), sliding window:

| Scope | Limit | Why |
| --- | --- | --- |
| `POST /api/chat` | 20 / min | Each call costs money; also the DoS surface |
| `POST /api/orders` | 5 / min | |
| `POST /api/auth/login` | 10 / 15 min per IP+email | Credential stuffing |
| `POST /api/auth/register` | 5 / hour per IP | |
| Read endpoints | 120 / min | |

`429` carries `Retry-After` and `X-RateLimit-Remaining`.

---

## 11. Versioning

Unversioned paths in v1. Additive changes (new fields, new event types, new error codes) ship
freely; clients must ignore unknowns. A breaking change introduces `/api/v2` alongside `/api`, with
v1 supported for 90 days. New error codes count as additive — which is why clients must have a
default branch for unrecognised codes.
