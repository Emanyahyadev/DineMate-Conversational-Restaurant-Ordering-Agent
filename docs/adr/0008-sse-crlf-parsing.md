# ADR-0008 — SSE frames are normalised before parsing, and tested on raw bytes

**Status:** Accepted · **Date:** 2026-09-07

## Context

For the whole of the first build the chat appeared broken in the browser: the
customer sent a message, the typing indicator ran, the turn completed, and no
reply ever appeared. The backend was fine — the same request over `httpx`
streamed a complete, correct answer in 18 seconds, and the reply was persisted
to Postgres every time.

The client is at fault, in one character. `sse-starlette` separates frames with
**CRLF**:

```
event: token\r\ndata: {"delta": "Hi"}\r\n\r\n
```

`streamChat` searched the buffer for `"\n\n"`. In `"\r\n\r\n"` the two newlines
are separated by a carriage return, so that search never matches. The parser
consumed the entire stream and produced **zero** frames. No `token` events, no
`cart` events, no `done` — the UI had nothing to render and no error to show.

## Why the tests did not catch it

`tests/integration/test_frontend_contract.py` asserted the SSE contract using
httpx's `aiter_lines()`, which normalises CRLF before the test ever sees it. The
test verified the *events* were correct while being structurally blind to the
*framing* — which was the only thing wrong. It passed on every run.

That is the real lesson here: a test that claims to cover a wire format must
read the wire. Anything that decodes for you is testing your decoder, not the
protocol.

## Decision

1. `streamChat` normalises `\r\n` to `\n` on every chunk before framing, strips a
   trailing `\r` from each line, and ignores `:` heartbeat comments. A trailing
   frame without a blank line after it is still emitted.
2. `tests/integration/test_sse_wire.py` asserts on `aiter_bytes()`, and one of
   its cases replays the browser's exact parsing steps against those bytes.

## Consequences

**Good:** the chat works, and the class of bug is now covered by a test that
cannot be fooled by a helpful client library. The parser also tolerates LF-only
framing, so swapping the SSE library will not break it.

**Bad:** a small amount of string work per chunk. Immaterial next to the network.

## Related

The same turn surfaced two other silent failures worth recording: the frontend
flipped a local flag inside a React state updater (React may invoke an updater
more than once, so the flag lied and appended replies went missing), and nothing
refreshed the 15-minute access token, so every request failed with "Please sign
in" once a session aged past it. Both are fixed in `frontend/src/lib/api.ts` and
`frontend/src/components/Chat.tsx`.
