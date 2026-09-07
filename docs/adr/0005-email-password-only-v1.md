# ADR-0005 — Email + password only in v1; no Google OAuth

**Status:** Accepted · **Date:** 2026-09-06 · **Decided by:** Project owner

## Context

[AUTH_SPEC.md](../AUTH_SPEC.md) §3 and [PRD.md](../PRD.md) US-25 both specify email+password
**and** Google OAuth. Before implementation the owner was asked whether to build OAuth now, defer
it, or wire it with real credentials, and chose **email + password only**.

## Decision

v1 ships email+password authentication. `oauth_accounts` is **not** created, and there is no
`/api/auth/oauth/*` route.

## Consequences

**Good:** one authentication path to build, test and attack-test. No dependency on Google's console,
no PKCE/state handling, no provider-email-verification edge cases. The 14-table schema is one table
smaller than [DATA_MODEL.md](../DATA_MODEL.md) §2 describes.

**Bad:** a customer with no password manager has one more password to remember, which is a real
conversion cost on a food-ordering site.

**Deviations recorded** (these documents describe the fuller design; the code deliberately
implements less):
- PRD US-25 — "register with email+password **or** Google" — only the first half is implemented.
- AUTH_SPEC §3 "Google OAuth" and §2's `password_hash IS NULL` OAuth-only account case.
- DATA_MODEL §2.1 `oauth_accounts` table, and the "password or ≥ 1 OAuth link" rule, which in v1
  reduces to "every active account has a password".

## Adding it later

`users.password_hash` is already nullable and `auth_service.verify_password` already returns False
for a null hash, so an OAuth-only account is representable without a migration to the `users` table.
Adding OAuth is: create `oauth_accounts`, add the two routes, add the button. No rework of session
handling, CSRF, or the tenancy model — none of which touch how the user proved who they are.
