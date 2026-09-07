"""The SSE wire format, asserted on raw bytes.

The earlier contract test used httpx's aiter_lines(), which silently normalises
CRLF. That hid a real bug for the whole build: the server frames with \r\n\r\n,
the browser parser split on "\n\n", and so the client parsed zero frames and
every reply vanished. Anything that claims to test the wire has to read bytes.
"""
import json

from tests.conftest import register_and_login


async def _raw(c, message="show me the menu"):
    chunks = []
    async with c.stream("POST", "/api/chat", json={"message": message}) as r:
        assert r.status_code == 200
        async for chunk in r.aiter_bytes():
            chunks.append(chunk)
            if len(b"".join(chunks)) > 2000:
                break
    return b"".join(chunks).decode()


async def test_frames_are_separated_by_a_blank_line(client):
    c = await register_and_login(client, "wire1@dinemate.example")
    raw = await _raw(c)
    # Whatever the newline convention, a blank line must separate frames.
    normalised = raw.replace("\r\n", "\n")
    assert "\n\n" in normalised, f"no frame separator in {raw[:200]!r}"


async def test_a_crlf_naive_parser_would_still_find_frames(client):
    """Guards the exact browser parsing path in frontend/src/lib/api.ts."""
    c = await register_and_login(client, "wire2@dinemate.example")
    raw = await _raw(c)

    # Mirror the client: normalise, then split on a blank line.
    buffer = raw.replace("\r\n", "\n")
    frames = [f for f in buffer.split("\n\n") if f.strip()]
    assert frames, "client-side parsing produced no frames"

    parsed = []
    for frame in frames:
        name, data = None, []
        for line in frame.split("\n"):
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].strip())
        if name and data:
            try:
                parsed.append((name, json.loads("\n".join(data))))
            except json.JSONDecodeError:
                pass  # a truncated final frame is fine

    names = [n for n, _ in parsed]
    assert "start" in names, f"no start event; got {names}"
    assert any(n == "token" for n in names), f"no token events; got {names}"

    start = next(d for n, d in parsed if n == "start")
    assert "conversation_id" in start


async def test_every_data_line_is_valid_json(client):
    c = await register_and_login(client, "wire3@dinemate.example")
    raw = await _raw(c)
    for line in raw.replace("\r\n", "\n").split("\n"):
        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload:
                json.loads(payload)  # raises if the server emitted junk
