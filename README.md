<div align="center">

  <img src="Logo.png" alt="DineMate Logo" width="220" />

  # DineMate — Conversational Restaurant Ordering Agent

  **Next-Generation Multi-Restaurant Ordering Platform with Intelligent Conversational AI, Dual-Tier Memory, Multi-Kitchen Dispatch, and Real-Time Kitchen Operations.**

  [![Next.js](https://img.shields.io/badge/Frontend-Next.js%2016%20(App%20Router)-black?style=for-the-badge&logo=next.js)](https://nextjs.org/)
  [![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
  [![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org/)
  [![TypeScript](https://img.shields.io/badge/TypeScript-5.0+-3178C6?style=for-the-badge&logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
  [![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16%20%2F%20Neon-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
  [![MongoDB](https://img.shields.io/badge/MongoDB-7.0%20%2F%20Atlas-47A248?style=for-the-badge&logo=mongodb&logoColor=white)](https://www.mongodb.com/)
  [![DeepSeek](https://img.shields.io/badge/LLM-DeepSeek%20%2F%20OpenAI%20SDK-4B0082?style=for-the-badge)](https://deepseek.com/)
  [![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)

</div>

---

## 📌 Overview

**DineMate** is an enterprise-ready conversational food ordering and restaurant management platform. Built on the **OpenAI Agents SDK** and backed by **DeepSeek LLM**, DineMate replaces static food ordering catalogs with a dynamic, context-aware AI agent that understands culinary nuances, dietary restrictions, spice preferences, and multi-dish cart orchestration across multiple partner restaurants.

### 🌟 Core Highlights
- 🧠 **Dual-Tier Memory Architecture:** Short-term conversational context stored in **PostgreSQL / Neon** with strict token budgets, plus long-term customer preference profiles in **MongoDB Atlas** with corroboration safeguards against hallucinations.
- 🏪 **Multi-Restaurant & Multi-Kitchen Grouping:** Supports multiple restaurant entities (Lahori Charga House, Karachi Seekh & Broast, Sindhi Biryani Co, Peshawari Namak Mandi, Chai Khana). Orders placed across kitchens are automatically partitioned into independent kitchen tickets.
- 👨‍🍳 **Staff Kitchen Portal:** Dedicated real-time dashboard for kitchen chefs to manage ticket lifecycles (`PENDING` ➔ `PREPARING` ➔ `READY` ➔ `DELIVERED`).
- 🛡️ **Zero-Bypass Security & Invariant Engine:** Hard gates ensuring the AI never invents prices/menu items, orders require cryptographic confirmation token consumption, money is calculated strictly in integer minor units (cents/paisa), and tenant data isolation is strictly enforced.
- ⭐ **Customer Experience:** Real-time order tracking, cancellation windows, interactive star ratings & review feedback loop, and full order history.

---

## 🏗️ System Architecture

```mermaid
flowchart TB
    subgraph ClientLayer["🖥️ Frontend (Next.js 16 + TypeScript + TailwindCSS v4)"]
        UI["💬 Chat UI & Stream Renderer<br/><code>src/components/Chat.tsx</code>"]
        CART_UI["🛒 Multi-Kitchen Cart Drawer<br/><code>src/components/CartPanel.tsx</code>"]
        KITCHEN_UI["👨‍🍳 Kitchen Staff Dashboard<br/><code>src/app/kitchen/page.tsx</code>"]
        ORDERS_UI["📦 Customer Order Tracking<br/><code>src/app/orders/page.tsx</code>"]
        API_CLIENT["⚡ Typed API Client<br/><code>src/lib/api.ts</code>"]
    end

    subgraph GatewayLayer["🚪 API & Security Gateway (FastAPI)"]
        AUTH["🔒 Session / JWT Verification<br/>(HttpOnly Cookie ➔ Trusted user_id)"]
        ROUTERS["🌐 API Endpoints<br/><code>/api/chat</code>, <code>/api/menu</code>, <code>/api/kitchen</code>, <code>/api/orders</code>"]
        ORCH["🎼 Turn Orchestrator<br/><code>agent/orchestrator.py</code>"]
    end

    subgraph AgentLayer["🤖 AI Agent Runtime (OpenAI Agents SDK)"]
        PROMPT["📜 Versioned System Prompt (v1.0.0)"]
        LLM["🧠 DeepSeek / OpenAI-Compatible Engine"]
        TOOLS["🛠️ Tool Adapter Layer<br/>(search_menu, update_cart, confirm_order)"]
    end

    subgraph DomainLayer["⚙️ Domain Services (Pure Business Logic)"]
        AUTH_SVC["auth_service"]
        MENU_SVC["menu_service"]
        CART_SVC["cart_service"]
        ORDER_SVC["order_service"]
        KITCHEN_SVC["kitchen_service"]
        RATING_SVC["rating_service"]
        MEM_SVC["memory_service"]
    end

    subgraph StorageLayer["💾 Storage & Persistence"]
        PG[("🐘 PostgreSQL / Neon<br/>Users, Restaurants, Menus,<br/>Carts, Orders, Conversations")]
        MONGO[("🍃 MongoDB Atlas<br/>Customer Preference Profiles,<br/>Long-term Memory Store")]
    end

    %% Client to Gateway
    UI & CART_UI & KITCHEN_UI & ORDERS_UI --> API_CLIENT
    API_CLIENT -->|"JWT Cookie + REST / SSE"| AUTH
    AUTH --> ROUTERS
    ROUTERS --> ORCH
    ROUTERS --> DomainLayer

    %% Agent Flow
    ORCH -->|"Assemble Prompt + History + Memory"| LLM
    LLM -->|"Function Calls"| TOOLS
    TOOLS --> DomainLayer
    LLM -->|"Token Stream"| ORCH
    ORCH -->|"SSE Stream"| UI

    %% Domain to Storage
    MENU_SVC & CART_SVC & ORDER_SVC & KITCHEN_SVC & RATING_SVC & AUTH_SVC --> PG
    MEM_SVC --> MONGO
    ORCH -.->|"Async Background Memory Extract"| MEM_SVC
```

---

## 🔄 Turn Lifecycle & Memory Flow

Every conversational interaction follows a strictly bounded, non-blocking sequence ensuring ultra-low latency while capturing durable customer memories:

```mermaid
sequenceDiagram
    autonumber
    actor User as 👤 Customer
    participant Web as 🌐 Next.js Frontend
    participant API as ⚡ FastAPI Gateway
    participant Orch as 🎼 Orchestrator
    participant PG as 🐘 PostgreSQL
    participant Mongo as 🍃 MongoDB
    participant LLM as 🧠 DeepSeek LLM
    participant Tools as 🛠️ Domain Tools

    User->>Web: "I'd like 2 Chicken Biryanis, make it spicy!"
    Web->>API: POST /api/chat (SSE stream request)
    API->>API: Validate JWT ➔ Extract trusted user_id
    API->>Orch: Run Turn (user_id, conversation_id, message)
    
    par Concurrent Context Assembly
        Orch->>PG: Fetch last 12 turns (Short-term context)
        Orch->>Mongo: Fetch preference profile (Long-term memory)
    end

    Orch->>LLM: Send System Prompt + Memory Block + History + User Message
    
    LLM->>Tools: Call search_menu(query='Chicken Biryani')
    Tools->>PG: Query active menu items (with restaurant scope)
    Tools-->>LLM: Return item metadata & price (minor units)
    
    LLM->>Tools: Call update_cart(items=[{item_id, qty: 2, notes: 'spicy'}])
    Tools->>PG: Update user cart & compute totals
    Tools-->>LLM: Return updated cart summary
    
    LLM-->>Orch: Stream generated response tokens
    Orch-->>Web: SSE Token deltas (Instant UI render)
    
    Orch->>PG: Save user message + assistant turn (single transaction)
    Orch-->>Web: SSE Done event (usage stats, conversation_id)
    
    Note over Orch,Mongo: Asynchronous Off-Path Memory Extraction (Zero Latency Penalty)
    Orch->>LLM: Analyze turn for durable preferences (spicy preference, dietary)
    LLM-->>Orch: Extracted fact: {"preference": "likes spicy Pakistani food"}
    Orch->>Mongo: Append / update corroborated customer memory
```

---

## 🏬 Multi-Kitchen Dispatch & Order Lifecycle

When a customer orders dishes from different culinary traditions (e.g., Karachi Grill + Chai Khana), DineMate handles multi-kitchen ordering seamlessly:

```mermaid
stateDiagram-v2
    [*] --> BuildingCart: Customer chats with AI
    BuildingCart --> ReviewCart: Items added across restaurants
    ReviewCart --> TokenIssued: User requests checkout (Token generated)
    TokenIssued --> OrderConfirmed: User confirms order (Token consumed)
    
    state OrderConfirmed {
        [*] --> SplitByKitchen: System partitions cart
        SplitByKitchen --> Ticket_Kitchen_A: Lahori Charga House
        SplitByKitchen --> Ticket_Kitchen_B: Sindhi Biryani Co
    }

    state TicketLifecycle {
        PENDING --> PREPARING: Kitchen Chef Accepts
        PREPARING --> READY: Chef Marks Ready
        READY --> DELIVERED: Order Handed Over
        PENDING --> CANCELLED: Customer Cancels (< 10 min window)
    }

    Ticket_Kitchen_A --> TicketLifecycle
    Ticket_Kitchen_B --> TicketLifecycle
    
    DELIVERED --> StarRating: Customer provides 1-5★ Rating & Review
    StarRating --> [*]
```

---

## 🗄️ Database & Storage Model

```mermaid
erDiagram
    USERS ||--o{ CARTS : owns
    USERS ||--o{ ORDERS : places
    USERS ||--o{ CONVERSATIONS : conducts
    RESTAURANTS ||--o{ MENU_ITEMS : offers
    RESTAURANTS ||--o{ ORDERS : fulfills
    CARTS ||--o{ CART_ITEMS : contains
    MENU_ITEMS ||--o{ CART_ITEMS : references
    ORDERS ||--o{ ORDER_ITEMS : contains
    MENU_ITEMS ||--o{ ORDER_ITEMS : references
    ORDERS ||--o| ORDER_RATINGS : receives
    CONVERSATIONS ||--o{ MESSAGES : logs

    USERS {
        uuid id PK
        string email UK
        string full_name
        string role "customer | staff | admin"
        uuid restaurant_id FK "nullable (for staff)"
    }

    RESTAURANTS {
        uuid id PK
        string name
        string slug UK
        string cuisine_type
        boolean is_active
    }

    MENU_ITEMS {
        uuid id PK
        uuid restaurant_id FK
        string name
        string category
        integer price_cents "Minor units"
        boolean is_available
    }

    ORDERS {
        uuid id PK
        uuid group_id "Multi-kitchen umbrella"
        uuid user_id FK
        uuid restaurant_id FK
        string status "PENDING | PREPARING | READY | DELIVERED | CANCELLED"
        integer total_amount_cents
        string confirmation_token
        timestamp created_at
    }

    ORDER_RATINGS {
        uuid id PK
        uuid order_id FK,UK
        integer rating "1 to 5"
        string review_text
        timestamp created_at
    }
```

---

## 💻 Tech Stack

| Tier | Technology | Purpose |
| :--- | :--- | :--- |
| **Frontend UI** | Next.js 16 (App Router), React 19, TypeScript | Server and Client components, live streaming chat, cart drawer, staff portal |
| **Styling** | TailwindCSS v4, Lucide Icons, Glassmorphic UI | Modern responsive dark-mode aesthetics |
| **Backend API** | FastAPI, Uvicorn, Python 3.12+ | Async REST & SSE streaming endpoints, auth cookies |
| **Package / Env** | `uv` (Fast Python Package Manager) | High-speed dependency management and reproducible virtual environments |
| **Agent Framework** | OpenAI Agents SDK | Tool definitions, run context injection, structured LLM loops |
| **LLM Inference** | DeepSeek (OpenAI-compatible endpoint) | Reasoning, menu search translation, conversational intelligence |
| **Relational DB** | PostgreSQL 16 / Neon | ACID transactions, users, menu catalog, cart items, order groups, message history |
| **Document DB** | MongoDB 7.0 / Atlas | Customer memory profiles, durable preference facts |
| **Migrations** | Alembic | Version-controlled, reproducible SQL database migrations |
| **Testing & Quality**| Pytest, Ruff, Mypy, Playwright | 250+ unit/integration/security tests, strict type checking |

---

## 🚀 Getting Started

### Prerequisites
- **Python 3.12+** & [**uv**](https://github.com/astral-sh/uv) installed
- **Node.js 20+** & **npm** / **pnpm**
- **Docker & Docker Compose** (for local databases)

---

### 1. Clone & Setup Infrastructure

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/restaurant-ordering-agent.git
cd restaurant-ordering-agent

# Start local PostgreSQL and MongoDB databases
docker compose up -d
```

---

### 2. Backend Setup

```bash
cd backend

# Copy environment template and configure keys
cp .env.example .env

# Edit backend/.env and provide:
# - DEEPSEEK_API_KEY=your_deepseek_key_here
# - POSTGRES_URL=postgresql+asyncpg://dinemate:dinemate@localhost:5433/dinemate
# - MONGODB_URL=mongodb://localhost:27018

# Run database migrations
uv run alembic upgrade head

# Seed initial restaurants, menu items, and demo accounts
uv run python -m app.cli seed-demo

# Start the FastAPI backend server (runs at http://localhost:8000)
uv run fastapi dev app/main.py
```

---

### 3. Frontend Setup

```bash
cd ../frontend

# Copy environment template
cp .env.example .env.local

# Install dependencies
npm install

# Start Next.js development server (runs at http://localhost:3000)
npm run dev
```

---

## 👥 Demo Accounts

The project includes pre-seeded demonstration accounts for immediate walkthrough:

> **Universal Demo Password:** `DineMate2026!Demo`

### 🛒 Customer Accounts (`http://localhost:3000`)
| Customer Name | Email | Persona / Role |
| :--- | :--- | :--- |
| **Ayesha Khan** | `ayesha.khan@dinemate.app` | Returning customer with Pakistani BBQ preferences |
| **Bilal Ahmed** | `bilal.ahmed@dinemate.app` | New customer with sweet-tooth & beverage preferences |

### 👨‍🍳 Kitchen Staff Accounts (`http://localhost:3000/kitchen`)
| Chef Name | Email | Assigned Kitchen |
| :--- | :--- | :--- |
| **Imran Malik** | `imran.lahori@dinemate.app` | *Lahori Charga House* |
| **Sana Qureshi** | `sana.karachi@dinemate.app` | *Karachi Seekh & Broast* |
| **Adnan Shah** | `adnan.sindhi@dinemate.app` | *Sindhi Biryani Co* |
| **Gulzar Khan** | `gulzar.peshawari@dinemate.app` | *Peshawari Namak Mandi* |
| **Nadia Iqbal** | `nadia.chaikhana@dinemate.app` | *Chai Khana* |

---

## 🛠️ AI Tools & Capabilities

The conversational agent operates strictly via structured tool execution:

| Tool Name | Parameters | Description |
| :--- | :--- | :--- |
| `search_menu` | `query`, `category`, `restaurant_id` | Full-text and fuzzy search across active, available menu items |
| `get_item_details` | `item_id` | Fetches ingredients, spice levels, allergens, and price in minor units |
| `get_cart` | *(injected from session)* | Retrieves the customer's current multi-kitchen basket |
| `update_cart_item` | `item_id`, `quantity`, `special_instructions` | Adds, updates quantity, or removes items from the cart |
| `request_confirmation` | *(injected from session)* | Computes taxes, verifies item availability, and issues a one-time token |
| `confirm_order` | `delivery_address`, `contact_phone` | Validates and consumes the confirmation token, creating kitchen tickets |
| `get_order_status` | `order_id` or `group_id` | Returns real-time preparation status and estimated delivery time |
| `cancel_order` | `order_id` | Allows order cancellation if within the active 10-minute window |

---

## 🛡️ Security & Architectural Invariants

1. **Zero Menu Hallucinations (A02):** The LLM has zero knowledge of prices or inventory in its system prompt. All prices and item availability originate from PostgreSQL tool lookups.
2. **One-Time Confirmation Token (A01):** Orders cannot be placed via standard chat turns without explicitly issuing and consuming a signed confirmation token (`confirm_order`).
3. **Session-Bound Identity (A03):** `user_id` is never accepted from the LLM arguments or client request bodies. It is extracted securely from the verified HTTP session JWT.
4. **Integer Minor Units:** All monetary values (PKR / USD cents) are stored, processed, and validated as integers to prevent floating-point rounding errors.
5. **Strict Multi-Tenant Isolation:** Kitchen staff hitting endpoints for an unassigned restaurant receive `404 Not Found` (never `403 Forbidden` to prevent resource enumeration).

---

## 🧪 Testing & Evaluation

The repository includes a comprehensive 250+ test suite and an LLM evaluation harness:

```bash
# Run all backend unit, integration, and security tests
cd backend
uv run pytest

# Run type checker and linter
uv run mypy app
uv run ruff check .

# Run prompt regression evaluation harness
uv run python -m evals.run --mode recorded
```

---

## 📂 Project Structure

```
├── backend/
│   ├── app/
│   │   ├── agent/             # OpenAI Agents SDK integration & prompt engineering
│   │   │   ├── orchestrator.py    # Turn orchestration, context assembler, SSE streaming
│   │   │   ├── restaurant_agent.py# Agent definition & system prompts
│   │   │   ├── tools.py           # Tool definitions & run context injection
│   │   │   └── prompts/           # Versioned system prompts (v1.0.0)
│   │   ├── api/               # FastAPI REST & SSE route handlers
│   │   │   ├── chat.py            # Conversational chat endpoint
│   │   │   ├── kitchen.py         # Kitchen ticket board routes
│   │   │   ├── menu.py            # Menu browsing & search
│   │   │   └── orders.py          # Order lifecycle & ratings
│   │   ├── db/                # PostgreSQL models and MongoDB clients
│   │   ├── services/          # Pure domain services (Cart, Order, Memory, Auth, Kitchen)
│   │   └── main.py            # FastAPI entrypoint & middleware configuration
│   ├── migrations/            # Alembic database migration scripts
│   ├── seeds/                 # Pakistani restaurant menu catalogs
│   └── tests/                 # Unit, integration, security, and tenancy test suites
├── frontend/
│   ├── src/
│   │   ├── app/               # Next.js 16 App Router pages (Chat, Kitchen, Orders, Profile)
│   │   ├── components/        # React components (Chat UI, CartPanel, MenuPanel, AuthGate)
│   │   └── lib/               # Typed API client and helpers
├── docs/                      # Architectural specs, API contracts, domain models, and runbooks
├── evals/                     # LLM golden dataset, eval harness, and scorecards
├── docker-compose.yml         # Local Postgres & Mongo container configuration
└── README.md                  # Project documentation
```

---

## 📄 License

This project is licensed under the **MIT License**. See the [LICENSE](LICENSE) file for details.

---

<div align="center">
  <sub>Built with ❤️ by the DineMate Engineering Team</sub>
</div>
