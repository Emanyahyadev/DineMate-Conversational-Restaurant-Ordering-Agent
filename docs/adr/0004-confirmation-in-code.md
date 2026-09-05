# ADR-0004 — Order confirmation enforced in code, not by prompt

**Status:** Accepted · **Date:** 2026-09-06 · **The most important decision in this project**

## Context

The agent must never place an order the customer did not agree to. [KPIS.md](../KPIS.md) A01 targets
**zero** unauthorized actions, as a hard gate.

The obvious implementation is a prompt instruction: *"Never call `confirm_order` unless the customer
explicitly agreed."* Models mostly comply. "Mostly" is the problem — at any real order volume, a
99.9% compliance rate means several wrong orders a week, each one a customer charged for food they
did not ask for, and each one impossible to prevent by asking the model more firmly.

The deeper issue is falsifiability. A prompt rule cannot be *verified*, only *sampled*. There is no
test that proves a model will never do the thing, because the input space is unbounded and
adversarial inputs are cheap to construct.

## Decision

Confirmation is enforced **structurally**, with the prompt as a secondary layer.

1. `view_cart` produces the itemised read-back **and** issues a confirmation token server-side. The
   token is bound to `(cart_id, cart_version, user_id)`, lives 5 minutes, and is single-use.
2. The token is **never given to the model**. It is held in server-side turn context.
3. `confirm_order` takes **no token parameter**. It reads the token from context; if there is none,
   it returns `NO_CONFIRMATION` and the model is told to read the cart back first.
4. Any cart mutation bumps `cart_version`, orphaning every outstanding token.
5. A token issued and consumed within the same turn is rejected — that is the "skipped the
   read-back" path.

## Rationale

**The model has no credential to forge.** It cannot mint a token, cannot replay one, and cannot pass
one it never sees. A jailbroken model, a prompt injection buried in a menu description, and a plain
bug all fail identically: no valid token, no order.

This turns an unfalsifiable behavioural claim into a checkable structural property. "Did an order
exist without a consumed token?" is a SQL query (INV-8), and it runs nightly as R08 and continuously
as the A01 online scorer.

The same reasoning applies to identity — the model has no `user_id` parameter, so it cannot express
the concept of another user ([AUTH_SPEC.md](../AUTH_SPEC.md) §5). Same principle, different noun.

## Alternatives considered

**Prompt-only.** Simplest, and unfalsifiable. Rejected on the grounds above.

**A confirmation *tool* the model calls first** (`request_confirmation` → `confirm_order`). Better,
but the model still controls both calls and can make them back to back without ever showing the
customer anything. Rejected: it moves the problem without solving it.

**Human-in-the-loop on every order.** Maximum safety, defeats the product.

**UI-only confirmation** (a button, never a typed "yes"). Safe, but forces the customer out of the
conversation to complete the one action the conversation exists for. Rejected — instead *both* paths
converge on the same server-side token check ([FRONTEND_SPEC.md](../FRONTEND_SPEC.md) §4).

## Consequences

**Good:** A01 = 0 is achievable and provable. Adversarial cases EV-ADV-04..06 pass because the
structure holds, not because the model behaved well. The mechanism is legible to future maintainers —
`confirm_order` has no token parameter, and the reason is right here.

**Bad:** more moving parts. A `confirmation_tokens` table, a context-passing mechanism, and a version
counter on carts. Worth it.

**Bad:** the model can hit `NO_CONFIRMATION` in a legitimate flow if it confirms without reading
back, which costs an extra turn. The prompt is written to avoid it and the eval set measures how
often it happens.

**Residual risk:** the model could call `view_cart` and `confirm_order` in one turn while showing the
customer nothing. Mitigated by disabling parallel tool calls, rejecting same-turn tokens, the prompt
rule, and eval cases — documented in [AGENT_SPEC.md](../AGENT_SPEC.md) §10 as low, and it is the one
place where a prompt rule still does load-bearing work.
