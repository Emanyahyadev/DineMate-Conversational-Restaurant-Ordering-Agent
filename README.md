# Restaurant Ordering Agent

Conversational ordering agent for a restaurant.

| Layer | Tech |
| --- | --- |
| Frontend | Next.js 16 (App Router, TypeScript, Tailwind v4) |
| Backend | FastAPI |
| Agent framework | OpenAI Agents SDK |
| LLM | DeepSeek (OpenAI-compatible endpoint) |
| Short term memory | Postgres / Neon (conversation turns) |
| Long term memory | MongoDB (preferences + personal info) |

## Layout

```
backend/
  app/
    main.py                     FastAPI app, CORS, lifespan
    config.py                   env-backed settings
    api/chat.py                 POST /api/chat, conversation + profile reads
    api/menu.py                 GET /api/menu
    agent/restaurant_agent.py   system prompt, agent build, memory extractor
    agent/tools.py              get_menu / place_order / order_status
    agent/menu.py               placeholder menu data
    db/postgres.py              conversations + messages (short term memory)
    db/mongo.py                 profiles + orders (long term memory)
frontend/
  src/app/page.tsx              chat page
  src/components/Chat.tsx       chat UI
  src/lib/api.ts                backend client
```

## Request flow

`user query → FastAPI → load short term history (Postgres) + long term memory (Mongo)
→ agent (DeepSeek + tools) → reply → persist turn → extract durable memories → Mongo`

## Running it

Backend:

```bash
cd backend
cp .env.example .env      # fill in DEEPSEEK_API_KEY, POSTGRES_URL, MONGODB_URL
uv run fastapi dev app/main.py   # http://localhost:8000
```

Frontend:

```bash
cd frontend
cp .env.example .env.local
npm run dev               # http://localhost:3000
```

`/health` and `/api/menu` work without any database; `/api/chat` needs Postgres, MongoDB,
and a DeepSeek key.

## Not built yet

- Auth (the frontend generates a random `user_id` in localStorage)
- Real menu/order persistence in Postgres (orders currently live in MongoDB)
- Streaming responses
