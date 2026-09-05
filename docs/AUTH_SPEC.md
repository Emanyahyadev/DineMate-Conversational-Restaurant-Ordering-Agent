# Authentication & Authorization

**Version:** 1.0.0 · Email+password and Google OAuth, from v1 (PRD US-25).

---

## 1. Why full accounts in v1

Long-term memory is the product differentiator, and memory without identity is either useless (lost
on every device change) or dangerous (a shared browser serving one customer another's allergy
profile and order history). A localStorage guest id — what the scaffold's `Chat.tsx` currently
generates — cannot support US-22 or US-24, and cannot make BC-4 true. Identity is therefore a v1
foundation, not a later addition.

---

## 2. Model

- **Access token** — JWT, 15 min, `HttpOnly; Secure; SameSite=Lax` cookie. Stateless; verified per
  request without a DB hit (keeps KPI P03 ≤ 150 ms).
- **Refresh token** — opaque 256-bit random, 30 days, `HttpOnly; Secure; SameSite=Strict`, path
  `/api/auth/refresh`. Stored **hashed** (SHA-256) in `sessions`; the raw value never touches the DB.
- **No tokens in JavaScript-readable storage.** httpOnly cookies mean an XSS cannot exfiltrate a
  session. The cost is CSRF exposure, handled in §6.

**Access JWT claims:** `sub` (user id), `sid` (session id), `iat`, `exp`, `iss`, `aud`. Nothing else
— no email, no roles, no display name. A JWT is a bearer credential that may sit in logs and proxies;
it carries the minimum to identify the caller.

Signing: HS256 with a 256-bit secret from the environment in v1, `kid` header included so a rotation
to RS256 needs no client change. Rotation procedure in [RUNBOOK.md](RUNBOOK.md) §7.

---

## 3. Flows

### Registration
1. Validate email shape; password ≥ 12 chars, checked against the top-10k breached list (length and
   breach status beat composition rules).
2. Hash with **Argon2id** (`m=64 MiB, t=3, p=4`).
3. Create `users` row, `email_verified_at` null.
4. Issue tokens — **unverified users may order**. Blocking on email verification loses customers at
   the exact moment they are hungry; verification gates only email-bearing actions (password reset,
   receipts).
5. Send the verification email (24 h single-use token).

### Login
Constant-time compare; identical response and timing for "no such user" and "wrong password".
On success: create a session, issue both cookies. Rate-limited 10 / 15 min per IP+email.

### Refresh rotation
Every refresh **rotates**: the old token is marked used and a new one issued. Presenting an
already-used refresh token means it was stolen and replayed — **revoke the entire session family and
force re-login**, then alert (`auth.refresh_reuse_detected`). This is the single highest-value
detection in the auth system.

### Google OAuth
Authorization code + **PKCE**, `state` bound to a signed short-lived cookie. On callback, link by
verified email if an account exists, else create one with `password_hash` null. An unverified email
from the provider is never auto-linked — that is an account-takeover path.

### Password reset
`POST /password/forgot` always returns `202`, whether or not the account exists (no enumeration
oracle). Token is single-use, 1 hour, stored hashed. A successful reset **revokes every session** —
if the reset was triggered by a compromise, leaving other sessions alive defeats the point.

### Logout
Revokes the current session only, clears both cookies. `POST /auth/logout/all` revokes every session
for the user.

---

## 4. Session lifecycle

| Event | Effect |
| --- | --- |
| Login / OAuth callback | New session row |
| Refresh | Rotate token, extend, same `sid` |
| Logout | `revoked_at` set |
| Password reset / change | All sessions revoked |
| Refresh reuse detected | All sessions revoked + alert |
| Account deletion | All sessions revoked, rows deleted |

Sessions are listable and individually revocable by the user (`GET`/`DELETE /api/auth/sessions`) —
`user_agent` and a **hashed** IP are shown; raw IPs are never stored.

---

## 5. Authorization

One rule, stated once, enforced in one place:

> **Every read and write is scoped to the caller's `user_id`, and `user_id` is taken only from the
> verified session.**

Mechanically:

1. Auth middleware verifies the access token → `request.state.user_id`.
2. Routes construct `ChatContext(user_id=...)` from that, never from the request body.
3. The context reaches tools via `RunContextWrapper[ChatContext]` — the pattern already correct in
   `backend/app/agent/tools.py`.
4. **Every domain-service method takes `user_id` as a required first argument** and filters on it.
   There is no service method that can be called without an owner, so a forgotten filter is a
   compile-time-visible mistake rather than a silent leak.
5. No tool accepts a `user_id` parameter. The model cannot express the concept of another user
   ([AGENT_SPEC.md](AGENT_SPEC.md) §5).

**Not-found over forbidden.** A foreign resource returns `NOT_FOUND`, never `FORBIDDEN` — a 403
confirms the resource exists and turns id-guessing into an enumeration oracle (US-18).

Test: `tests/security/test_tenancy.py` creates two users, has user B attempt every route and every
tool against user A's ids, and asserts `NOT_FOUND` with zero of A's field values in the body. This
backs hard-gate KPI A03.

---

## 6. CSRF

httpOnly cookies are sent automatically, so state-changing requests need a second factor:

- `SameSite=Lax` on the access cookie blocks cross-site POSTs from ordinary navigation.
- **Double-submit token** on every mutating request: a non-httpOnly `csrf_token` cookie must equal
  the `X-CSRF-Token` header. The frontend client in `src/lib/api.ts` attaches it centrally.
- The refresh cookie is `SameSite=Strict`, path-scoped to `/api/auth/refresh`.
- CORS: exact-origin allowlist with `allow_credentials=True`. The current
  `allow_origins=settings.cors_origins` in `backend/app/main.py` is correct in shape; it must never
  become `["*"]`, which silently disables credentialed CORS anyway.

---

## 7. Attack posture

| Threat | Control |
| --- | --- |
| Credential stuffing | Rate limit 10 / 15 min per IP+email; breached-password check at registration; lockout-free (avoids a DoS-by-lockout) |
| Token theft via XSS | httpOnly cookies; strict CSP ([FRONTEND_SPEC.md](FRONTEND_SPEC.md) §9); no `dangerouslySetInnerHTML` on model output |
| Refresh replay | Rotation + reuse detection + family revocation (§3) |
| Session fixation | New session id on every login |
| Account enumeration | Uniform responses and timing on login, forgot-password, and OAuth link |
| Privilege escalation via the model | Model has no `user_id` channel (§5) |
| Brute-force reset tokens | 256-bit, hashed, single-use, 1 h |
| Email change takeover | Requires current password + verification at the new address (v2 feature; not in v1) |

---

## 8. Scaffold deltas

| Now | Target |
| --- | --- |
| `Chat.tsx` generates `user-<random>` in localStorage | Real accounts; `user_id` never leaves the server |
| `ChatRequest.user_id` accepted from the request body (`app/api/chat.py`) | **Removed** — body-supplied identity is a forgery path |
| No auth middleware | JWT verification on every `/api` route except menu and auth |
| `/api/profile/{user_id}` path parameter | `/api/profile` — always the caller |

The third row is the important one: today anyone can pass any `user_id` and read that person's
profile. It is harmless in a local scaffold with no real users and no exposed port, and it is
exactly the class of bug this spec exists to make impossible. Fixed in M2.

---

## 9. Configuration

```
JWT_SECRET=                # 256-bit, rotated quarterly
JWT_ISSUER=restaurant-agent
ACCESS_TOKEN_TTL_SECONDS=900
REFRESH_TOKEN_TTL_DAYS=30
GOOGLE_OAUTH_CLIENT_ID=
GOOGLE_OAUTH_CLIENT_SECRET=
PASSWORD_RESET_TTL_SECONDS=3600
COOKIE_DOMAIN=
COOKIE_SECURE=true         # false only for local http
```

Startup refuses to boot in production if `JWT_SECRET` is unset, shorter than 32 bytes, or equal to a
known development default — a weak signing key silently forges every account.
