# ADR-0009 — Staff identity lives on the account, not in a shared secret

**Status:** Accepted · **Date:** 2026-09-07 · **Supersedes:** the
`/internal/orders/{id}/status` stand-in from [API_CONTRACT.md](../API_CONTRACT.md) §7

## Context

[PRD.md](../PRD.md) §3 listed a staff-facing kitchen display as a v1 non-goal, and
order status was advanced by an internal endpoint behind a shared header secret.
The owner asked for real dashboards: a queue per restaurant, order status, and
the ability to take a dish off.

A shared secret is fine for a seed script and wrong for people. It cannot say
*which* kitchen is asking, so it cannot stop one restaurant advancing another's
tickets, and it cannot be revoked for one person.

## Decision

Staff are ordinary accounts with two extra columns:

```sql
role                TEXT NOT NULL DEFAULT 'customer'  -- 'customer' | 'staff'
staff_restaurant_id TEXT REFERENCES restaurants(id)
CHECK ((role = 'staff') = (staff_restaurant_id IS NOT NULL))
```

That CHECK is the whole design in one line. Staff without a kitchen could see
everything; a customer with one would be staff by accident. Neither state is
allowed to exist, so neither has to be defended against in application code.

**No route under `/api/kitchen` takes a restaurant id.** It is read from the
caller's account, exactly as `user_id` is on the customer side — the same
reasoning as [ADR-0004](0004-confirmation-in-code.md): what cannot be named
cannot be forged.

`require_staff` raises **NOT_FOUND**, not FORBIDDEN, for a customer. A 403 would
confirm the kitchen surface exists and invite probing.

## What the dashboard does

- **Queue** — live tickets ordered by stage then age, flagged late past 25 minutes.
- **Advance** — moves a ticket along. Rule L1 still holds: `order_service.transition`
  refuses an illegal move whether it came from a customer or a chef.
- **Today** — orders, revenue, cancellations, and the dishes going out most.
- **86 board** — take a dish off. The menu cache is invalidated on the spot, so
  the agent stops offering it on the next turn rather than up to a minute later.

## Consequences

**Good:** every kitchen sees only its own work, enforced by the same rule the rest
of the system uses. Staff can be created, moved and revoked per person
(`python -m app.cli staff <email> <restaurant> <password>`). The internal
shared-secret endpoint is now only a seeding convenience.

**Bad:** one more axis on the auth model. It is covered by
`tests/security/test_kitchen_tenancy.py`, which asserts a customer gets 404, a
kitchen never sees another kitchen's ticket, and neither can 86 a dish that is
not theirs.

**Deviation recorded:** PRD §3 named this a non-goal. It was built at the owner's
request; the PRD's release criteria are unchanged, and the dashboard is not
gated by them.
