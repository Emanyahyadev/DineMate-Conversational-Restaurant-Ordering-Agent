# ADR-0007 — Tool arguments are coerced, not strictly validated

**Status:** Accepted · **Date:** 2026-09-07

## Context

With the real model wired up, every conversation ended in silence. The customer
sent a message, the typing indicator ran, and nothing ever came back.

The cause was one line of JSON. `search_menu` declares
`dietary_tags: array<string>`; the model sent:

```json
{"query": "vegetarian", "category": "Pizza", "restaurant_id": "",
 "dietary_tags": "vegetarian", "limit": 3}
```

A bare string where the schema demands an array. The Agents SDK validated the
arguments, rejected the call, and handed the model an error. The model tried
again, made the same formatting choice, and the loop continued until the run hit
its turn limit — at which point the whole turn failed. The tool body never ran,
so nothing was logged as a tool call and the failure looked like a hang.

`restaurant_id: ""` was a second instance of the same class: an empty string
where "not specified" was meant.

## Decision

The tool layer coerces argument shapes before validating meaning
(`_as_list` and `_as_text` in `backend/app/agent/tools.py`):

- a bare string becomes a one-element list, and `"a, b"` becomes `["a", "b"]`
- an empty or whitespace string becomes `None`, meaning "no filter"
- the affected parameters are typed `Any` so the SDK does not reject them first

The agent loop also gets a turn cap (`MAX_AGENT_TURNS`, default 6) and, on
exceeding it, emits an honest `AGENT_STALLED` message rather than leaving the
customer with a spinner.

## Rationale

Strictness at this boundary buys nothing. A model that writes `"vegetarian"`
instead of `["vegetarian"]` has communicated its intent perfectly clearly; the
only thing rejection achieves is turning a formatting slip into a dead
conversation. This is the one place in the system where being liberal is right:
the argument is a *request*, not a fact, and no safety property depends on its
shape.

Everything that does carry a guarantee stays strict. Ownership still comes from
the session, `confirm_order` still needs a server-issued token, quantities are
still bounded, and money is still integer cents. Coercion happens on the way in;
the domain rules downstream are unchanged.

## Consequences

**Good:** the agent answers. Model-specific formatting quirks stop being outages,
and a stalled loop now says so.

**Bad:** the JSON schema advertised to the model is slightly less honest than the
Python signature, since `Any` is what the SDK sees for those parameters. The
tool descriptions still say what is expected, and the eval suite asserts the
*coerced* values, so a genuinely wrong argument is still caught by KPI A05.
