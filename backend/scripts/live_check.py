import asyncio
import time
import uuid
import sys
import pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from agents import Runner

from app.agent.context import ChatContext
from app.agent.runtime import build_agent
from app.db.models import User
from app.db.postgres import SessionLocal


async def turn(uid, history, msg):
    async with SessionLocal() as s:
        ctx = ChatContext(user_id=uid, session=s, turn_id=uuid.uuid4().hex)
        t0 = time.time()
        try:
            r = await Runner.run(build_agent("Nothing on file for this customer yet."),
                                 [*history, {"role": "user", "content": msg}], context=ctx)
            out = r.final_output
        except Exception as e:
            out = f"[ERROR {type(e).__name__}: {e}]"
        await s.commit()
        el = time.time() - t0
    print(f">>> USER: {msg}", flush=True)
    print(f"    tools: {[t['name'] for t in ctx.tool_calls]}   ({el:.0f}s)", flush=True)
    print(f"    DINEMATE: {str(out)[:400]}\n", flush=True)
    return history + [{"role":"user","content":msg},{"role":"assistant","content":str(out)}]

async def main():
    async with SessionLocal() as s:
        u = User(email=f"live{uuid.uuid4().hex[:6]}@dinemate.example", password_hash="x", status="active")
        s.add(u); await s.commit(); uid = u.id
    print(f"user {uid}\n", flush=True)
    h = []
    for msg in ["Hi! What vegetarian mains do you have?",
                "I'll take two Margherita pizzas please",
                "that's everything",
                "yes, place the order"]:
        h = await turn(uid, h, msg)
    from sqlalchemy import select

    from app.db.models import Order
    async with SessionLocal() as s:
        rows = await s.execute(select(Order).where(Order.user_id == uid))
        for o in rows.scalars():
            print(f"ORDER {o.id} status={o.status} total={o.total}", flush=True)

asyncio.run(main())
