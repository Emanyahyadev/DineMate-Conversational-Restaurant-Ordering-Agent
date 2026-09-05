# Frontend Specification

**Version:** 1.0.0 · Next.js 16 (App Router) · TypeScript · Tailwind v4

---

## 1. Stance

The chat is the primary interface, but **the cart is not a chat message**. Anything the customer is
about to be charged for gets a persistent, visible, non-conversational representation. A scrolled-
away read-back is not informed consent, and the UI carries as much of BC-2 as the backend does.

Three rules the UI must never break:
1. The cart is always visible or one tap away, and always reflects server state.
2. Placing an order requires a deliberate action — a button press or an unambiguous typed
   confirmation — never an inferred one.
3. Prices shown come from `*_display` strings the server computed. **The frontend never does money
   arithmetic** (Rule $1).

---

## 2. Routes

| Route | Auth | Purpose |
| --- | --- | --- |
| `/` | public | Landing + menu preview; CTA into chat |
| `/chat` | required | The agent. Redirects to `/login?next=/chat` |
| `/chat/[conversationId]` | required | A past conversation |
| `/menu` | public | Browsable menu (non-conversational path, and the SEO surface) |
| `/orders` | required | Order history |
| `/orders/[id]` | required | Detail + status timeline |
| `/profile` | required | Account, and **memory management** (US-24) |
| `/login`, `/register`, `/forgot`, `/reset` | public | Auth |

Server Components by default; `"use client"` only where interaction demands it (the chat surface,
cart panel, forms). The menu page is statically rendered with a 60 s revalidate — it matches the
server-side menu cache and is what makes P07 (LCP ≤ 2.0 s) achievable.

---

## 3. Component tree (chat)

```
app/chat/page.tsx                  server: session, initial conversation, initial cart
└── <ChatSurface>                  client: owns turn state
    ├── <MessageList>              virtualised above 50 messages
    │   ├── <Message role="user">
    │   ├── <Message role="assistant">   streamed text
    │   └── <ToolIndicator>              "Checking the menu…"
    ├── <Composer>                 textarea, send, disabled while streaming
    ├── <CartPanel>                sidebar ≥1024px, bottom sheet below
    │   ├── <CartLine>             qty stepper, remove
    │   └── <CartSummary>          subtotal / tax / total, all from *_display
    └── <ConfirmDialog>            explicit, modal, focus-trapped
```

`src/components/Chat.tsx` in the scaffold becomes `<ChatSurface>`; its message-list and composer
concerns split out. The `useUserId` localStorage hook is **deleted** — identity comes from the
session ([AUTH_SPEC.md](AUTH_SPEC.md) §8).

---

## 4. Ordering interaction

The critical path, and the place where UI and safety meet.

```mermaid
sequenceDiagram
    participant C as Customer
    participant UI
    participant API
    C->>UI: "that's everything"
    UI->>API: POST /api/chat (SSE)
    API-->>UI: token stream (itemised read-back)
    API-->>UI: event: cart  {cart, confirmation_token}
    UI->>UI: CartPanel highlights; "Place order — $24.30" button enables
    alt Customer taps the button
        C->>UI: tap
        UI->>UI: ConfirmDialog — full itemisation, focus trapped
        C->>UI: confirm
        UI->>API: POST /api/orders {confirmation_token} + Idempotency-Key
        API-->>UI: 201 order
    else Customer types "yes"
        C->>UI: "yes, place it"
        UI->>API: POST /api/chat
        Note over API: agent calls confirm_order with the server-side token
    end
```

Both paths converge on the same server-side token check. The button is the **primary** path because
it is unambiguous; the typed path exists because forcing a customer out of the conversation to click
would defeat the product. Neither can produce an order without a valid token.

**The button is disabled** whenever no valid token exists — empty cart, cart edited since the
read-back, or token expired. Its disabled tooltip states which, so the customer is never left
guessing why they cannot order.

---

## 5. Streaming UX

Consuming the SSE contract in [API_CONTRACT.md](API_CONTRACT.md) §4:

| Event | UI |
| --- | --- |
| `start` | Assistant bubble appears with a cursor; conversation id bound to the URL |
| `token` | Text appended; **no per-token re-layout** — the bubble reserves height to avoid CLS |
| `tool` | `<ToolIndicator>` shows the human label; hidden on `phase: end` |
| `cart` | Cart panel updates immediately — never wait for `done` |
| `done` | Cursor removed; composer re-enabled; message committed to local state |
| `error` | Inline error inside the bubble with a **Retry** button; text so far is preserved, never discarded |

Unknown event types are ignored (forward compatibility). Reconnection: on transport drop, one
automatic retry; if it fails, an explicit "connection lost — retry" affordance. Never silently drop a
half-streamed reply, and never auto-resend a message that may already have been processed.

**Perceived latency:** the composer clears and the user's message renders optimistically on submit,
so the interface responds in < 100 ms regardless of TTFT.

---

## 6. State

| State | Owner | Notes |
| --- | --- | --- |
| Session/user | Server Component + `/auth/me` | Never in localStorage |
| Messages | `<ChatSurface>` local | Server-hydrated on load |
| Streaming buffer | `<ChatSurface>` local | Transient |
| **Cart** | Server, mirrored from `cart` SSE events and mutation responses | **Never** derived from chat text |
| Menu | RSC fetch, 60 s revalidate | |
| Orders | RSC fetch per route | |

No global state library. The only genuinely shared state is the cart, and the server is its owner —
`cart` events plus full-cart mutation responses keep the mirror truthful without reconciliation
logic.

**Optimistic updates** apply to cart quantity steppers only (instant feedback, revert on error).
Never to order placement — an optimistic order is a lie about money.

---

## 7. Accessibility (WCAG 2.2 AA)

- **Streaming announcements:** the assistant bubble is `aria-live="polite" aria-atomic="false"`,
  announced on sentence boundaries rather than per token — per-token announcement makes a screen
  reader unusable.
- **Full keyboard path:** browse → add → review → confirm, with no pointer. Tested in e2e
  ([TEST_STRATEGY.md](TEST_STRATEGY.md) §8).
- `<ConfirmDialog>` traps focus, is labelled by its heading, restores focus on close, closes on Esc.
- Tool indicators are `aria-busy` regions, not decorative-only spinners.
- Contrast ≥ 4.5:1 including the amber accent on white (the scaffold's `bg-amber-600` with white
  text passes; amber on light backgrounds for *text* does not — use `amber-700` there).
- Targets ≥ 44×44 px. Visible focus rings; never `outline: none` without a replacement.
- `prefers-reduced-motion` disables streaming cursor animation and transitions.
- Errors are announced, associated with their control via `aria-describedby`, and never colour-only.

---

## 8. Responsive

| Breakpoint | Layout |
| --- | --- |
| < 640 px | Single column; cart as a bottom sheet with a persistent total bar |
| 640–1023 px | Single column; cart in a slide-over |
| ≥ 1024 px | Two columns: chat + persistent cart sidebar |

**Supported range: 320–2560 px.** 375 px is the design target (PRD US-28); 320 px must remain usable,
not merely unbroken. No horizontal scroll at any width — wide content (long item names, the read-back
table) wraps or scrolls inside its own container, never the page body.

Mobile-first, because a hungry person on a phone is the primary persona:

- **Composer above the keyboard** via `dvh` units and `interactive-widget=resizes-content`; the
  latest message scrolls into view after send (US-30).
- **Persistent total bar** whenever the cart is non-empty, so the amount is never more than a glance
  away (US-29) — a total the customer cannot see is not informed consent.
- **`<ConfirmDialog>` scrolls internally** at small heights; lines and total are never clipped.
- **Touch targets ≥ 44 × 44 px**, including the quantity steppers, which are the most common
  small-target mistake.
- **Body text ≥ 16 px** in chat and cart — below that, iOS Safari zooms on focus and the layout
  breaks.
- **Orientation change preserves** composer content and cart state.
- Both themes are verified at every breakpoint; a dark-mode-only overflow is still an overflow.

---

## 9. Security

- **Model output is rendered as text.** A constrained Markdown renderer (bold, italic, lists, line
  breaks) with HTML disabled. No `dangerouslySetInnerHTML` on anything the model produced, ever.
- CSP: `default-src 'self'`, no inline scripts, no external origins. Blocks exfiltration even if an
  injection succeeds.
- No secrets in the bundle — only `NEXT_PUBLIC_API_URL`. CI greps the build output.
- CSRF token attached centrally in `src/lib/api.ts` ([AUTH_SPEC.md](AUTH_SPEC.md) §6).
- Auth cookies are httpOnly; the client never reads a token.

---

## 10. Performance

Targets P07 (LCP ≤ 2.0 s), P08 (INP ≤ 200 ms), P09 (≤ 180 kB first-load JS).

- Server Components everywhere except the chat surface, cart, and forms.
- No component library; Tailwind + a handful of local primitives. This is the main reason P09 is
  reachable.
- `next/font` with the existing Geist setup (self-hosted, no layout shift).
- Message list virtualised above 50 messages.
- Streamed text appends to a single text node — no re-render per token.
- Reserved bubble height and fixed-size skeletons keep CLS ≈ 0.
- Route-level code splitting; `/chat` does not ship `/orders` code.

---

## 11. Error and empty states

Every view specifies all four states. No spinners without context, no dead ends.

| Surface | Loading | Empty | Error |
| --- | --- | --- | --- |
| Chat | Skeleton bubbles | Greeting + three suggested openers | Inline, retryable |
| Cart | Skeleton lines | "Nothing yet — ask me what's good" | Refresh action |
| Menu | Skeleton grid | "Menu unavailable right now" — **never an invented menu** | Retry |
| Orders | Skeleton rows | "No orders yet" + CTA | Retry |
| Auth forms | Button spinner | — | Field-level + form-level |

The `LLM_UNAVAILABLE` case shows an honest "I can't reach the kitchen's brain right now" with a
retry — matching BC-7 in the UI layer, so a backend failure never surfaces as silence.

---

## 12. Design tokens

Building on the scaffold's `globals.css`. Amber (`amber-600` / `amber-700`) as the accent — warm,
food-adjacent, and distinct from the destructive red.

```css
:root {
  --background: #ffffff;  --foreground: #171717;
  --surface: #fafafa;     --border: rgb(0 0 0 / 0.10);
  --accent: #d97706;      /* amber-600 — buttons, user bubbles */
  --accent-text: #b45309; /* amber-700 — accent-coloured text, contrast-safe */
  --danger: #dc2626;      --success: #16a34a;
  --radius: 1rem;
}
@media (prefers-color-scheme: dark) {
  :root { --background: #0a0a0a; --foreground: #ededed;
          --surface: #141414; --border: rgb(255 255 255 / 0.12); }
}
```

Both themes are specified because the scaffold already ships a dark block and a half-themed app
looks broken. Every colour pair is contrast-checked in both.

---

## 13. Scaffold deltas

| Now | Target |
| --- | --- |
| `useUserId` localStorage id | Deleted — session-based identity |
| Request/response `sendMessage` | SSE consumption |
| No cart UI | `<CartPanel>` + `<ConfirmDialog>` |
| Hand-written types in `src/lib/api.ts` | Generated from OpenAPI |
| Single `Chat.tsx` | Split per §3 |
| No auth routes | `/login`, `/register`, `/forgot`, `/reset` |
| Message content rendered as plain text | Constrained Markdown renderer (§9) |
