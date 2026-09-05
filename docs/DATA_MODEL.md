# Data Model

**Version:** 1.0.0 · Postgres 16 (Neon) + MongoDB 7 (Atlas)

Implements [DOMAIN_MODEL.md](DOMAIN_MODEL.md). Every rule referenced as `Rule Xn` or `INV-n` comes
from there.

---

## 1. The split, and why

| Store | Holds | Why |
| --- | --- | --- |
| **Postgres** | users, sessions, menu, carts, **orders**, conversations, messages | Anything needing transactions, foreign keys, or a correct total. Order confirmation is a multi-table atomic write (Rule R1) — the one thing a document store makes hard |
| **MongoDB** | memory profiles | Schema-free, per-user, append-heavy documents whose shape will change as the memory policy evolves. No cross-document consistency requirement |

**Scaffold delta — orders move.** `backend/app/db/mongo.py` currently owns an `orders` collection.
That was a scaffolding shortcut. Orders are money and state: they need INV-4 (total consistency),
INV-6 (event per transition), and INV-8 (no order without a consumed token) — all of which are
foreign-key-and-transaction problems. Rationale recorded in
[ADR-0002](adr/0002-postgres-mongo-split.md).

---

## 2. Postgres schema

Conventions: `TIMESTAMPTZ` everywhere (never naive), money as `INTEGER` minor units (Rule $1), UUIDv7
primary keys except where a human-speakable id is required, `citext` for email.

### 2.1 Identity

```sql
CREATE EXTENSION IF NOT EXISTS citext;

CREATE TABLE users (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email             CITEXT      NOT NULL UNIQUE,
    password_hash     TEXT,                       -- NULL for OAuth-only accounts
    display_name      TEXT,
    email_verified_at TIMESTAMPTZ,
    status            TEXT        NOT NULL DEFAULT 'active'
                      CHECK (status IN ('active','suspended','deleted')),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE oauth_accounts (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider          TEXT NOT NULL CHECK (provider IN ('google')),
    provider_user_id  TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (provider, provider_user_id)
);

CREATE TABLE sessions (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id            UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    refresh_token_hash TEXT NOT NULL UNIQUE,      -- SHA-256; the raw token is never stored
    user_agent         TEXT,
    ip_hash            TEXT,                      -- hashed, not raw (privacy)
    expires_at         TIMESTAMPTZ NOT NULL,
    revoked_at         TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

> **Rule without a constraint:** an active account must have either a `password_hash` or ≥ 1 linked
> OAuth account. This deliberately has no CHECK — a row-level CHECK cannot see `oauth_accounts`.
> `auth_service` enforces it, and [TEST_STRATEGY.md](TEST_STRATEGY.md) §3 carries the service-level
> test. Do not try to express it in DDL.

### 2.2 Menu

```sql
CREATE TABLE menu_items (
    id            TEXT PRIMARY KEY,                     -- speakable, stable (Rule M1)
    name          TEXT    NOT NULL,
    description   TEXT    NOT NULL DEFAULT '',
    category      TEXT    NOT NULL CHECK (category IN
                  ('Starters','Pizza','Pasta','Salad','Sides','Dessert','Drinks')),
    base_price    INTEGER NOT NULL CHECK (base_price > 0),   -- minor units (Rule $1)
    dietary_tags  TEXT[]  NOT NULL DEFAULT '{}',
    allergens     TEXT[]  NOT NULL DEFAULT '{}',
    allergens_verified BOOLEAN NOT NULL DEFAULT false,       -- Rule M3
    is_available  BOOLEAN NOT NULL DEFAULT true,             -- 86'd today
    is_active     BOOLEAN NOT NULL DEFAULT true,             -- soft delete
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX menu_items_name_active_uq
    ON menu_items (lower(name)) WHERE is_active;             -- Rule M1: unique within active menu

CREATE TABLE menu_option_groups (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    menu_item_id TEXT NOT NULL REFERENCES menu_items(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    min_select   SMALLINT NOT NULL DEFAULT 0 CHECK (min_select >= 0),
    max_select   SMALLINT NOT NULL DEFAULT 1,
    sort_order   SMALLINT NOT NULL DEFAULT 0,
    CHECK (max_select >= min_select)
);

CREATE TABLE menu_options (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    option_group_id UUID NOT NULL REFERENCES menu_option_groups(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    price_delta     INTEGER NOT NULL DEFAULT 0,              -- may be negative (Rule O2)
    is_available    BOOLEAN NOT NULL DEFAULT true,
    sort_order      SMALLINT NOT NULL DEFAULT 0
);
```

### 2.3 Cart

```sql
CREATE TABLE carts (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    version    INTEGER NOT NULL DEFAULT 0,                   -- bumped on every mutation (§3 protocol)
    status     TEXT NOT NULL DEFAULT 'open'
               CHECK (status IN ('open','confirmed','abandoned')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- INV-3: at most one open cart per user
CREATE UNIQUE INDEX carts_one_open_per_user ON carts (user_id) WHERE status = 'open';

CREATE TABLE cart_lines (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cart_id      UUID NOT NULL REFERENCES carts(id) ON DELETE CASCADE,
    menu_item_id TEXT NOT NULL REFERENCES menu_items(id),
    quantity     SMALLINT NOT NULL CHECK (quantity BETWEEN 1 AND 20),   -- INV-2 / Rule C2
    note         TEXT NOT NULL DEFAULT '',
    options_hash TEXT NOT NULL DEFAULT '',                   -- for the merge rule (C1)
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Rule C1: identical item + identical options collapse to one line
CREATE UNIQUE INDEX cart_lines_dedupe ON cart_lines (cart_id, menu_item_id, options_hash);

CREATE TABLE cart_line_options (
    cart_line_id   UUID NOT NULL REFERENCES cart_lines(id) ON DELETE CASCADE,
    menu_option_id UUID NOT NULL REFERENCES menu_options(id),
    PRIMARY KEY (cart_line_id, menu_option_id)
);

CREATE TABLE confirmation_tokens (
    token        TEXT PRIMARY KEY,                           -- opaque, 256-bit
    cart_id      UUID NOT NULL REFERENCES carts(id) ON DELETE CASCADE,
    user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    cart_version INTEGER NOT NULL,                           -- stale version ⇒ invalid (US-15)
    expires_at   TIMESTAMPTZ NOT NULL,                       -- issued_at + 5 min
    consumed_at  TIMESTAMPTZ,                                -- single use
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX confirmation_tokens_cart ON confirmation_tokens (cart_id) WHERE consumed_at IS NULL;
```

### 2.4 Orders

```sql
CREATE TABLE orders (
    id              TEXT PRIMARY KEY,                        -- 'ORD-123456', non-sequential (Rule R3)
    user_id         UUID NOT NULL REFERENCES users(id),
    status          TEXT NOT NULL DEFAULT 'confirmed' CHECK (status IN
                    ('confirmed','preparing','ready','out_for_delivery','completed','cancelled')),
    fulfilment      TEXT NOT NULL DEFAULT 'pickup' CHECK (fulfilment IN ('pickup','delivery')),
    subtotal        INTEGER NOT NULL CHECK (subtotal >= 0),  -- all minor units (Rule $1-$3)
    tax             INTEGER NOT NULL CHECK (tax >= 0),
    delivery_fee    INTEGER NOT NULL DEFAULT 0,
    total           INTEGER NOT NULL CHECK (total >= 0),
    payment_method  TEXT NOT NULL DEFAULT 'on_delivery',     -- v1: no PSP (PRD §3)
    notes           TEXT NOT NULL DEFAULT '',
    idempotency_key TEXT UNIQUE,                             -- replay-safe confirm
    confirmed_at    TIMESTAMPTZ NOT NULL DEFAULT now(),      -- starts the cancellation window (L2)
    cancelled_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT orders_total_consistent CHECK (total = subtotal + tax + delivery_fee)   -- INV-4
);

CREATE TABLE order_lines (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id      TEXT NOT NULL REFERENCES orders(id) ON DELETE RESTRICT,   -- Rule R4: never deleted
    menu_item_id  TEXT NOT NULL REFERENCES menu_items(id),
    item_name     TEXT    NOT NULL,                          -- snapshot (Rule R2)
    unit_price    INTEGER NOT NULL CHECK (unit_price >= 0),  -- snapshot
    quantity      SMALLINT NOT NULL CHECK (quantity BETWEEN 1 AND 20),
    line_total    INTEGER NOT NULL CHECK (line_total >= 0),
    options_json  JSONB   NOT NULL DEFAULT '[]',             -- snapshot of chosen options
    note          TEXT    NOT NULL DEFAULT '',
    CONSTRAINT order_lines_total_consistent CHECK (line_total = unit_price * quantity)  -- Rule $2
);

CREATE TABLE order_events (
    id          BIGSERIAL PRIMARY KEY,
    order_id    TEXT NOT NULL REFERENCES orders(id) ON DELETE RESTRICT,
    from_status TEXT,
    to_status   TEXT NOT NULL,
    actor       TEXT NOT NULL CHECK (actor IN ('customer','staff','system')),
    reason      TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX order_events_order ON order_events (order_id, created_at);
```

INV-5 (every order has ≥ 1 line) is enforced in `order_service` inside the confirm transaction — a
deferred constraint would be the alternative, but the service already owns the transaction.

### 2.5 Conversations

```sql
CREATE TABLE conversations (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title      TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE messages (
    id              BIGSERIAL PRIMARY KEY,
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user','assistant')),   -- Rule V2
    content         TEXT NOT NULL,
    prompt_version  TEXT,                                    -- which prompt produced it
    trace_id        TEXT,                                    -- joins to OTel
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Tool calls are **not** rows here (Rule V2) — they live as spans in tracing. This keeps the history
read cheap and the prompt bounded.

---

## 3. MongoDB

Single collection, `profiles`, `_id` = the Postgres `users.id` as a string. The link is by
convention, not constraint — hence Rule N-cleanup in §6.

```javascript
{
  _id: "9f1c…",                      // users.id
  preferences: [
    { id: "p_01", text: "Vegetarian", source_message_id: 8412,
      confidence: 0.95, created_at: ISODate(), last_seen_at: ISODate() }
  ],
  facts: [
    { id: "f_01", text: "Allergic to peanuts", kind: "allergy",   // Rule N3
      source_message_id: 8412, confidence: 0.99, created_at: ISODate() }
  ],
  stats: { orders_placed: 12, last_order_at: ISODate() },
  updated_at: ISODate(),
  schema_version: 1
}
```

Rules: entries are append-with-dedupe (never blind overwrite); `kind: "allergy"` entries are
never auto-expired and require an explicit user action to delete (Rule N3); a deny-list filter
rejects payment, ID, location, and non-allergy health content before write (Rule N2, INV-10);
`schema_version` makes future migrations possible without a downtime window.

**Indexes:** `{ _id }` (implicit) is sufficient — every access is by user. A TTL index is
deliberately *not* used: memory expires by policy, not by clock.

**Scaffold delta.** Current `profiles` documents hold bare strings in `preferences`/`facts`. The
object form above is required for US-24 (delete a specific memory, which needs an id) and for
precision measurement (KPI A08, which needs provenance). Migration: wrap existing strings into
objects with `confidence: null`, `schema_version: 1`.

---

## 4. Seed menu

The eight items currently hard-coded in `backend/app/agent/menu.py` become
`backend/seeds/menu.yaml`, loaded by `python -m app.cli seed-menu`. Code stops being the menu's home
— the eval fixtures and the ops team both need to change it without a deploy. `menu.py` is deleted
in M1.

---

## 5. Indexes

Each exists to serve a named query. No speculative indexes.

| Index | Serves | Budget |
| --- | --- | --- |
| `carts_one_open_per_user` (partial unique) | open-cart lookup on every cart tool + INV-3 | < 1 ms |
| `cart_lines_dedupe` (unique) | Rule C1 merge-on-add | < 1 ms |
| `messages (conversation_id, id DESC)` | last-12-turns read, every turn | < 5 ms |
| `orders (user_id, confirmed_at DESC)` | "my recent orders" (US-17) | < 5 ms |
| `orders (status) WHERE status IN ('confirmed','preparing','ready')` partial | ops queue | < 5 ms |
| `order_events (order_id, created_at)` | status history | < 5 ms |
| `menu_items (category) WHERE is_active AND is_available` partial | menu search, cached 60 s | < 2 ms |
| `menu_items (lower(name)) WHERE is_active` unique | Rule M1 + name resolution | < 2 ms |
| `confirmation_tokens (cart_id) WHERE consumed_at IS NULL` partial | token validation on confirm | < 1 ms |
| `sessions (refresh_token_hash)` unique | refresh rotation | < 2 ms |

All within KPI P04 (DB query p95 ≤ 50 ms).

---

## 6. Retention, privacy, deletion

| Data | Retention | On account deletion |
| --- | --- | --- |
| `messages`, `conversations` | 90 days rolling | Deleted immediately |
| `orders`, `order_lines`, `order_events` | 7 years (tax) | **Retained, anonymised** — `user_id` repointed to a tombstone user; names/notes scrubbed |
| `carts` | 24 h after last touch (Rule C4) | Deleted |
| `sessions` | Until expiry | Revoked and deleted |
| Mongo `profiles` | Until user deletes | Deleted immediately |
| OTel traces | 30 days | Contain no PII by construction ([OBSERVABILITY.md](OBSERVABILITY.md) §4) |

Deletion is a job — `python -m app.cli delete-user <id>` — that spans both stores and is verified by
an integration test. Because Mongo has no FK to Postgres, that job is the *only* thing keeping the
two consistent; a weekly reconciliation task reports orphaned profile documents.

---

## 7. Migrations

**Alembic**, from M1. `Base.metadata.create_all` in `backend/app/db/postgres.py` is deleted — it
silently diverges from migrations and there is no worse production surprise. Rules: one migration per
PR that touches the schema; every migration has a tested `downgrade`; expand/contract for
destructive changes (add nullable → backfill → switch reads → drop) so a deploy is never coupled to
a migration; CI asserts `alembic upgrade head` on a blank DB matches the models
(`alembic check`).

Mongo has no migration tool; `schema_version` plus a read-time upgrade function handles the two
transitions foreseen.

---

## 8. Invariant enforcement map

| Invariant | Enforced by |
| --- | --- |
| INV-1 item active when added | `cart_service.add_line` + FK |
| INV-2 quantity 1–20 | CHECK on `cart_lines` and `order_lines` |
| INV-3 one open cart | `carts_one_open_per_user` partial unique index |
| INV-4 total consistency | `orders_total_consistent` CHECK |
| INV-5 order has ≥ 1 line | `order_service.confirm` (in-transaction) |
| INV-6 event per transition | `order_service.transition` (same transaction) |
| INV-7 legal transitions only | `order_service` state machine |
| INV-8 no order without a token | `order_service.confirm` + `confirmation_tokens.consumed_at` |
| INV-9 every row has an owner | `NOT NULL` FKs to `users` |
| INV-10 no denied memory categories | `memory_service` deny-list filter |

Each row has a test in [TEST_STRATEGY.md](TEST_STRATEGY.md) §3.
