# ADR-0003 — Server-Sent Events for chat streaming

**Status:** Accepted · **Date:** 2026-09-06

## Context

The scaffold's `POST /api/chat` returns a complete reply. A DeepSeek turn with tool calls takes
several seconds, so the customer stares at "Thinking…" for the entire generation. KPI P01 requires
time-to-first-token p95 ≤ 2.5 s, which a request/response endpoint cannot satisfy — its TTFT *is* its
total duration.

## Decision

Stream with **Server-Sent Events** over the same `POST /api/chat`, with typed events: `start`,
`token`, `tool`, `cart`, `done`, `error` ([API_CONTRACT.md](../API_CONTRACT.md) §4).

## Rationale

The traffic is one-directional. The client sends one message and then only listens; the next message
is a new request. That is precisely SSE's shape, and it buys:

- **Plain HTTP** — no upgrade handshake, works through corporate proxies and CDNs that mishandle
  WebSocket upgrades.
- **Automatic reconnection** in the browser's `EventSource` semantics.
- **Stateless servers** — any instance can serve any request; no sticky sessions, no connection
  affinity, so horizontal scaling stays trivial.
- **Trivially debuggable** — `curl` shows the stream. WebSocket frames need tooling.
- **Fits FastAPI** — `sse-starlette` is already a transitive dependency of the installed stack.

WebSockets would give bidirectionality we do not need, in exchange for connection state, heartbeat
management, sticky routing, and a harder debugging story.

## Alternatives considered

**WebSocket** — right choice if we later add typing indicators from other participants, live order
tracking pushed from the kitchen, or multi-party conversations. None are in v1
([PRD.md](../PRD.md) §3). Revisit when kitchen-pushed status lands.

**HTTP chunked / streaming JSON** — works, but no event types, so the client parses a bespoke frame
format. SSE gives that for free.

**Long polling** — higher latency, more requests, no benefit.

## Consequences

**Good:** P01 becomes achievable — first token in under a second while generation continues; tool
progress (`tool` events) and cart updates (`cart` events) reach the UI mid-turn, so the cart panel is
never stale.

**Bad:** POST-based SSE means the browser's native `EventSource` (GET-only) cannot be used — the
client uses `fetch` with a `ReadableStream` reader and implements reconnection itself. That is
~40 lines in `src/lib/api.ts`, and it is why [FRONTEND_SPEC.md](../FRONTEND_SPEC.md) §5 specifies the
reconnection behaviour explicitly rather than leaving it to the platform.

**Bad:** errors after streaming begins cannot use an HTTP status — the status is already sent. Hence
the `error` **event** inside a 200 response, which clients must handle as a terminal outcome.

**Operational:** proxies must not buffer (`X-Accel-Buffering: no`), and a `:ping` comment every 15 s
keeps idle intermediaries from closing the stream.
