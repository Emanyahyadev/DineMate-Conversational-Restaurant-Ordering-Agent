# Deploying DineMate

The short version: **the Next.js frontend goes on Vercel, the FastAPI backend does not.**
Everything below follows from that split.

`app/deployment.py` enforces the rules here at startup — in production a bad
configuration refuses to boot rather than failing later in the browser as
something that looks unrelated. `tests/unit/test_deployment.py` pins each rule.

---

## 1. Why the backend is not on Vercel

Vercel runs serverless functions. Three things about this backend fight that model:

| What the backend does | What serverless does to it |
| --- | --- |
| Streams a chat turn over SSE for 5-60s | Function time limits cut the stream mid-reply |
| Holds a Postgres pool per process | Every cold start opens new connections; Neon's limit is reached quickly |
| Caches the menu and a Mongo client in-process | Discarded on each invocation, so the caches never warm |

Run it as a **container** instead — Render, Railway, Fly.io, Cloud Run — where the
process is long-lived. That is what the pooling and caching in this codebase assume.

The frontend is a good fit for Vercel: it is a static/SSR Next.js app that talks
to the API over HTTP.

---

## 2. The cookie problem (the one that actually bites)

The frontend on `dinemate.vercel.app` and the API on `api.example.com` are
**different sites**. Session cookies are `SameSite=Lax` by default, and a Lax
cookie is *not sent on cross-site requests*. The symptom is not an error message:
sign-in appears to work, then every subsequent request is `401`, and it looks like
a login bug.

Two ways out. Pick one.

**A. Same site (preferred).** Serve the frontend and API under one registrable
domain — `app.dinemate.com` and `api.dinemate.com`, or proxy `/api` through the
frontend host. Then:

```
COOKIE_SAMESITE=lax
COOKIE_SECURE=true
```

**B. Genuinely cross-site.** Only if A is impossible:

```
COOKIE_SAMESITE=none
COOKIE_SECURE=true     # browsers reject SameSite=None without it
CORS_ORIGINS=["https://dinemate.vercel.app"]
PUBLIC_API_URL=https://api.dinemate.app
```

Note what B costs: the refresh token drops from `SameSite=Strict` to `None`, so
the CSRF double-submit token is doing more of the work. Prefer A.

`PUBLIC_API_URL` is what lets the startup check tell A from B. Set it.

> Ports are irrelevant to SameSite — `localhost:3000` and `localhost:8000` are the
> same site. **Hosts are not**: a cookie set for `localhost` is never sent to
> `127.0.0.1`. Keep `NEXT_PUBLIC_API_URL` on the same host as the page, in
> development too.

---

## 3. Neon

Use the **`-pooler`** host, always. The direct endpoint allows far fewer
connections than even a two-instance deployment opens, and the failure is
intermittent under load rather than immediate.

```
POSTGRES_URL=postgresql+asyncpg://user:pass@ep-xxx-pooler.region.aws.neon.tech/neondb?sslmode=require
```

The engine already handles what the pooler requires (`app/db/postgres.py`):

- `statement_cache_size=0` — PgBouncer in transaction mode hands each query a
  different server connection, so asyncpg's prepared statements are invisible on
  the next one and queries hang or fail.
- `pool_recycle=300` — Neon suspends idle computes and PgBouncer recycles
  connections; an older pooled connection is likely already dead at the far end.
- `pool_pre_ping=True` — checks before handing a connection out.

Size the pool against Neon's limit **divided by the number of workers**:

```
PG_POOL_SIZE=5          # per worker
PG_MAX_OVERFLOW=10      # per worker
```

Two instances × two workers × (5+10) = 60 connections. Lower these before raising
the worker count.

Migrations run **before** the new code, as a separate step — never on startup:

```
alembic upgrade head
```

### Latency

**Put the database in the region the API runs in.** Everything else on this page
is a rounding error next to it. Measured against a Neon branch in `us-east-2`
from South Asia, one round trip costs ~0.5 s, and *a round trip is the unit that
matters* — not query cost, not CPU. The same code against a same-region or local
Postgres is not slow.

Because a round trip is that expensive, the app is written to spend as few as it
can, and it is easy to undo by accident:

- **No relationship is loaded that is not used.** `Restaurant.items`,
  `MenuItem.restaurant` and `MenuItem.option_groups` are all `lazy="selectin"`,
  and they refer to each other — so one `select(Restaurant)` used to issue six
  statements and read the entire menu to display a restaurant's name. The hot
  read paths pass explicit `noload()`/`contains_eager()` options. If you add a
  query on a read path, check the statement count, not just the SQL.
- **Read endpoints do not open a transaction** (`get_read_db` in `app/api/deps.py`).
  `BEGIN` and `COMMIT` are a round trip each and buy nothing around a `SELECT`.
- **Aggregates that share a window share a query** (`kitchen_service.stats`,
  `rating_service.scorecard_for`).

Two settings are a straight latency-for-reliability trade, and both are worth
revisiting per deployment:

| Setting | Costs | Buys |
| --- | --- | --- |
| `PG_POOL_PRE_PING=true` | ~0.9 s per request on a distant database (one round trip) | A suspended Neon compute surfaces as a slow request, not a failed one |
| the `-pooler` host | ~2.4× per query — PgBouncer forces `statement_cache_size=0`, so asyncpg sends Parse and Execute separately | Connection headroom, which a serverless or multi-instance deployment genuinely needs |

Keep both as they are for a serverless deployment against Neon. A single
long-lived API process with its own connection pool, next to its database, wants
neither.

---

## 4. MongoDB Atlas

Mongo holds only the long-term memory profiles. It is a *degradable* dependency:
if it is unreachable the agent still takes orders, it just does not remember
anything. Do not make it a health-check blocker.

```
MONGODB_URL=mongodb+srv://user:pass@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority
MONGODB_DB=dinemate
MONGO_MAX_POOL_SIZE=10
```

Add the container platform's egress IPs to the Atlas allowlist. Atlas defaults to
denying everything, and the resulting timeout looks like the 2s server-selection
timeout rather than an access error.

The client is cached **per event loop, weakly** (`app/db/mongo.py`): Motor binds a
client to the loop that created it, and a weak-keyed map lets the entry go when
the loop does.

---

## 5. Environment variables

Backend:

| Variable | Notes |
| --- | --- |
| `POSTGRES_URL` | Neon, `-pooler` host |
| `MONGODB_URL`, `MONGODB_DB` | Atlas |
| `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `LLM_MODEL` | The agent cannot answer without a key |
| `JWT_SECRET` | Must not be the development default |
| `INTERNAL_SECRET` | Guards the internal status route |
| `COOKIE_SECURE`, `COOKIE_SAMESITE`, `COOKIE_DOMAIN` | Section 2 |
| `CORS_ORIGINS`, `PUBLIC_API_URL` | Exact origins; never `*` with credentials |
| `PG_POOL_SIZE`, `PG_MAX_OVERFLOW`, `MONGO_MAX_POOL_SIZE` | Section 3, 4 |
| `ENVIRONMENT=production` | Turns the startup check from warning into refusal |

Frontend (Vercel project settings):

| Variable | Notes |
| --- | --- |
| `NEXT_PUBLIC_API_URL` | `https://api.…` — public, so no secrets here |

---

## 6. Before you call it deployed

1. `alembic upgrade head` ran and exited 0.
2. The app started **without** deployment warnings in the log.
3. `GET /health` is 200.
4. Register, sign out, sign back in — in a real browser, on the real domain.
   This is the check that catches the cookie problem, and nothing else does.
5. Place an order spanning two kitchens; confirm both order ids come back.
6. Advance a ticket on `/kitchen`; confirm the customer's `/orders` page follows
   it without a manual reload.
7. `python -m app.cli check-invariants` reports 0 violations.
