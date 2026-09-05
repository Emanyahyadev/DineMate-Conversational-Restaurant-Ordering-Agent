# ADR-0002 — Postgres for state, MongoDB for memory; orders move to Postgres

**Status:** Accepted · **Date:** 2026-09-06 · **Supersedes:** the scaffold's `orders` collection

## Context

The architecture brief specifies both Postgres (short-term memory) and MongoDB (long-term memory).
The scaffold implemented that, but also put **orders** in MongoDB — a convenience, since
`place_order` already had a Mongo handle.

Orders are the one thing in this system that must be exactly right. They carry money, they have a
state machine with legal and illegal transitions, they must never be duplicated by a network retry,
and every transition must be auditable. [DOMAIN_MODEL.md](../DOMAIN_MODEL.md) INV-4 through INV-8
are all transactional or referential properties.

## Decision

**Postgres** is authoritative for users, sessions, menu, carts, **orders**, order lines, order
events, conversations, and messages.

**MongoDB** holds exactly one thing: per-user memory profiles.

Orders move out of MongoDB in M1.

## Rationale

Order confirmation is a single atomic operation across five tables: validate the confirmation token,
snapshot the cart lines with current prices, insert the order, insert its lines, insert the event,
clear the cart, consume the token. Either all of it happens or none of it does
([DOMAIN_MODEL.md](../DOMAIN_MODEL.md) Rule R1).

In Postgres that is `BEGIN … COMMIT` and two CHECK constraints. In MongoDB it is either a multi-
document transaction (available, but bolted onto a model that does not want it) or application-level
compensation logic — which is where the "we lost an order" bugs live. KPI R05 has a target of zero,
and a design where zero requires hand-written rollback code is the wrong design.

Memory has the opposite shape: no cross-document consistency requirement, a schema that will change
as the memory policy evolves, and per-user documents that are only ever read whole. That is what a
document store is good at, and the `schema_version` field makes its evolution cheap.

## Alternatives considered

**Everything in Postgres.** Genuinely defensible — `JSONB` would serve memory perfectly well, and one
store means one backup story, one connection pool, one failure mode. Rejected because the brief
specifies both stores and because memory's schema churn is real. **If the two-store cost proves
higher than expected — the cross-store deletion job in [DATA_MODEL.md](../DATA_MODEL.md) §6 is the
main tax — collapsing to Postgres is a clean future ADR.**

**Everything in MongoDB.** Rejected: order integrity, above.

**Orders in both (Postgres authoritative, Mongo denormalised).** Rejected: two sources of truth for
money, and a reconciliation problem nobody asked for.

## Consequences

**Good:** transactional integrity where it matters; FK constraints catch whole classes of bug at
write time; INV-4 and the state machine are enforced by the database rather than by hope.

**Bad:** two stores to run, back up, and monitor. No referential integrity between a Mongo profile
and its Postgres user — the `delete-user` job and a weekly orphan-reconciliation task exist purely to
cover that gap.

**Migration:** the scaffold's `orders` collection holds no production data. Drop it; no migration
needed. The `profiles` collection needs its string entries wrapped into objects
([DATA_MODEL.md](../DATA_MODEL.md) §3).
