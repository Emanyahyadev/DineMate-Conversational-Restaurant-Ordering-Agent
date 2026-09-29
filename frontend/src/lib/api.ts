/**
 * The only place the app talks to the DineMate backend.
 *
 * Identity lives in httpOnly cookies, so every request is `credentials:
 * "include"` and mutations carry the double-submit CSRF header. Nothing here
 * ever computes money: the server sends `*_cents` and a `*_display` string, and
 * the UI renders the display string verbatim (DOMAIN_MODEL Rule $5).
 */

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/* ---------------------------------------------------------------- types */

export type User = {
  id: string;
  email: string;
  display_name: string | null;
  email_verified: boolean;
  created_at: string | null;
  role: "customer" | "staff";
  staff_restaurant_id: string | null;
};

export type MenuItem = {
  id: string;
  restaurant_id: string;
  restaurant_name: string;
  name: string;
  description: string;
  category: string;
  dietary_tags: string[];
  allergens: string[];
  allergens_verified: boolean;
  is_available: boolean;
  price_cents: number;
  price_display: string;
};

export type MenuResponse = { items: MenuItem[]; categories: string[] };

export type CartLine = {
  line_id: string;
  item_id: string;
  name: string;
  restaurant_id: string;
  restaurant_name: string;
  quantity: number;
  note: string;
  options: { id: string; name: string; price_delta_cents: number }[];
  unit_price_cents: number;
  unit_price_display: string;
  line_total_cents: number;
  line_total_display: string;
};

/** What this restaurant's own customers scored it. `average` is null until
 *  somebody has actually rated a completed order there. */
export type RatingSummary = { average: number | null; count: number };

export type Rating = {
  id: string;
  order_id: string;
  stars: number;
  comment: string;
  customer: string | null;
  created_at: string | null;
};

export type Restaurant = {
  id: string;
  name: string;
  cuisine: string;
  description: string;
  item_count: number;
  categories: string[];
  dietary_tags: string[];
  rating: RatingSummary;
};

export type CartGroup = {
  restaurant_id: string;
  restaurant_name: string;
  lines: CartLine[];
  subtotal_cents: number;
  subtotal_display: string;
};

export type Cart = {
  id: string | null;
  version: number;
  /** A basket may span kitchens; each becomes its own order at checkout. */
  restaurants: CartGroup[];
  restaurant_count: number;
  lines: CartLine[];
  subtotal_cents: number;
  subtotal_display: string;
  tax_cents: number;
  tax_display: string;
  total_cents: number;
  total_display: string;
};

export type OrderLine = {
  item_id: string;
  name: string;
  quantity: number;
  unit_price_display: string;
  line_total_display: string;
};

export type Order = {
  id: string;
  /** Shared by every order from one checkout. */
  order_group_id: string | null;
  contact_phone: string;
  delivery_address: string;
  restaurant_id: string | null;
  restaurant_name: string;
  status: string;
  fulfilment: string;
  lines: OrderLine[];
  subtotal_display: string;
  tax_display: string;
  total_display: string;
  total_cents: number;
  notes: string;
  confirmed_at: string;
  cancellable_until: string;
  eta_minutes: number;
  events?: {
    from_status: string | null;
    to_status: string;
    actor: string;
    created_at: string;
  }[];
  /** Present once the customer has rated this order. */
  rating?: Rating | null;
  /** Completed, and not yet rated. */
  can_rate?: boolean;
};

export type Memory = {
  id: string;
  text: string;
  kind: string | null;
  created_at: string | null;
};

export class ApiError extends Error {
  code: string;
  status: number;
  constructor(code: string, message: string, status: number) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

/* -------------------------------------------------------------- plumbing */

function csrfToken(): string {
  if (typeof document === "undefined") return "";
  const match = document.cookie.match(/(?:^|;\s*)dm_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

/**
 * Refresh the access token at most once at a time.
 *
 * Access tokens last 15 minutes. Without this, a customer who spends longer
 * than that choosing dinner finds every button silently failing with "Please
 * sign in" - which is what happened before this existed.
 */
let refreshing: Promise<boolean> | null = null;

async function refreshSession(): Promise<boolean> {
  refreshing ??= (async () => {
    try {
      const r = await fetch(`${API_URL}/api/auth/refresh`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
      });
      return r.ok;
    } catch {
      return false;
    } finally {
      // Cleared on the next tick so concurrent callers share this attempt.
      setTimeout(() => {
        refreshing = null;
      }, 0);
    }
  })();
  return refreshing;
}

async function send(path: string, init: RequestInit): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((init.headers as Record<string, string>) ?? {}),
  };
  if (method !== "GET" && method !== "HEAD") headers["X-CSRF-Token"] = csrfToken();
  return fetch(`${API_URL}${path}`, { credentials: "include", ...init, headers });
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res = await send(path, init);

  // One transparent retry after refreshing an expired access token.
  if (res.status === 401 && !path.startsWith("/api/auth/")) {
    if (await refreshSession()) res = await send(path, init);
  }

  if (res.status === 204) return undefined as T;

  const body = await res.text();
  const parsed = body ? JSON.parse(body) : null;

  if (!res.ok) {
    const err = parsed?.error;
    throw new ApiError(
      err?.code ?? "INTERNAL_ERROR",
      err?.message ?? `Request failed (${res.status})`,
      res.status,
    );
  }
  return parsed as T;
}

/* ------------------------------------------------------------------ auth */

export const register = (email: string, password: string, display_name?: string) =>
  request<{ user: User }>("/api/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password, display_name: display_name || null }),
  });

export const login = (email: string, password: string) =>
  request<{ user: User }>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });

export const logout = () => request<void>("/api/auth/logout", { method: "POST" });

export const me = () => request<{ user: User }>("/api/auth/me");

/* ------------------------------------------------------------------ menu */

export type MenuBoard = {
  items: MenuItem[];
  categories: string[];
  restaurants: Restaurant[];
};

/**
 * The whole browse surface in one request.
 *
 * This used to fetch the restaurant list, then one capped page of /api/menu per
 * restaurant, then the list again for the ratings - seven serial-ish round
 * trips before the first dish appeared, because /api/menu is sized for the
 * agent rather than for a human scrolling a menu. /api/menu/full is served from
 * the same cache the agent reads and answers all of it at once.
 */
export const fetchMenuBoard = () => request<MenuBoard>("/api/menu/full");

/* ------------------------------------------------------------------ cart */

export type Greeting = {
  greeting: string;
  name: string | null;
  known_allergens: string[];
  known_preferences: string[];
  returning: boolean;
};

export type ConversationSummary = {
  id: string;
  title: string;
  updated_at: string | null;
  empty: boolean;
};

/* --------------------------------------------------------------- kitchen */

export type KitchenOrder = Order & {
  waiting_minutes: number;
  is_late: boolean;
  next_statuses: string[];
};

export type KitchenStats = {
  orders_today: number;
  cancelled_today: number;
  revenue_today_cents: number;
  revenue_today_display: string;
  live_by_status: Record<string, number>;
  top_items: { name: string; quantity: number }[];
};

export type KitchenMenuItem = {
  id: string;
  name: string;
  description: string;
  category: string;
  dietary_tags: string[];
  is_available: boolean;
  price_display: string;
  price_cents: number;
};

export type NewDish = {
  name: string;
  category: string;
  price: string;
  description?: string;
  dietary_tags?: string[];
};

export const kitchenMe = () =>
  request<{
    staff: { id: string; email: string; name: string | null };
    restaurant: { id: string; name: string; cuisine: string };
  }>("/api/kitchen/me");

export const kitchenOrders = () =>
  request<{ items: KitchenOrder[]; stats: KitchenStats }>("/api/kitchen/orders");

export const kitchenHistory = () =>
  request<{ items: Order[] }>("/api/kitchen/orders/history");

/** Answers with the moved ticket in board shape, so the row can be swapped in
 *  place rather than the whole queue re-read. */
export const advanceOrder = (id: string, to_status: string) =>
  request<{ order: KitchenOrder }>(`/api/kitchen/orders/${id}/advance`, {
    method: "POST",
    body: JSON.stringify({ to_status, reason: "" }),
  });

export const kitchenMenu = () =>
  request<{ items: KitchenMenuItem[] }>("/api/kitchen/menu");

export const addDish = (dish: NewDish) =>
  request<{ item: KitchenMenuItem }>("/api/kitchen/menu", {
    method: "POST",
    body: JSON.stringify(dish),
  });

export const menuCategories = () =>
  request<{ items: string[]; dietary_tags: string[] }>("/api/kitchen/menu/categories");

export const kitchenRatings = () =>
  request<{
    summary: RatingSummary;
    distribution: Record<string, number>;
    recent: Rating[];
  }>("/api/kitchen/ratings");

export const rateOrder = (orderId: string, stars: number, comment: string) =>
  request<{ rating: Rating }>(`/api/orders/${orderId}/rating`, {
    method: "POST",
    body: JSON.stringify({ stars, comment }),
  });

export const setItemAvailability = (id: string, is_available: boolean) =>
  request<{ item: KitchenMenuItem }>(`/api/kitchen/menu/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ is_available }),
  });

export const getGreeting = () => request<Greeting>("/api/greeting");

export const listConversations = () =>
  request<{ items: ConversationSummary[] }>("/api/conversations");

export const newConversation = () =>
  request<{ id: string }>("/api/conversations", { method: "POST" });

export const getConversation = (id: string) =>
  request<{ id: string; messages: { role: "user" | "assistant"; content: string }[] }>(
    `/api/conversations/${id}`,
  );

export const deleteConversation = (id: string) =>
  request<void>(`/api/conversations/${id}`, { method: "DELETE" });

export const listRestaurants = () =>
  request<{ items: Restaurant[] }>("/api/restaurants");

export type CartResponse = {
  cart: Cart;
  confirmation_token: string | null;
  /** Saved from the last order, so a returning customer is not asked twice. */
  contact: { phone: string; address: string };
  delivery_fee_display: string;
};

export const getCart = () => request<CartResponse>("/api/cart");

export const addToCart = (item_id: string, quantity = 1) =>
  request<{ cart: Cart }>("/api/cart/lines", {
    method: "POST",
    body: JSON.stringify({ item_id, quantity }),
  });

export const setLineQuantity = (line_id: string, quantity: number) =>
  request<{ cart: Cart }>(`/api/cart/lines/${line_id}`, {
    method: "PATCH",
    body: JSON.stringify({ quantity }),
  });

export const clearCart = () => request<{ cart: Cart }>("/api/cart", { method: "DELETE" });

/* ---------------------------------------------------------------- orders */

export type Checkout = {
  fulfilment: "pickup" | "delivery";
  contact_phone: string;
  delivery_address: string;
  notes: string;
};

export const placeOrder = (confirmation_token: string, checkout: Checkout) =>
  request<{ orders: Order[]; order: Order }>("/api/orders", {
    method: "POST",
    // Idempotency-Key is what makes a retried confirm safe to send (KPI R05).
    headers: { "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify({ confirmation_token, ...checkout }),
  });

export const listOrders = () => request<{ items: Order[] }>("/api/orders");

export const getOrder = (id: string) => request<{ order: Order }>(`/api/orders/${id}`);

export const cancelOrder = (id: string, reason = "") =>
  request<{ order: Order }>(`/api/orders/${id}/cancel`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });

/* --------------------------------------------------------------- profile */

export const getProfile = () =>
  request<{ user: User; stats: { orders_placed: number; last_order_at: string | null } }>(
    "/api/profile",
  );

export const getMemories = () =>
  request<{ preferences: Memory[]; facts: Memory[] }>("/api/profile/memories");

export const forgetMemory = (id: string) =>
  request<void>(`/api/profile/memories/${id}`, { method: "DELETE" });

/* ------------------------------------------------------------------ chat */

export type ChatEvent =
  | { type: "start"; conversation_id: string; turn_id: string }
  | { type: "token"; delta: string }
  | { type: "tool"; name: string; phase: "start" | "end"; label: string }
  | { type: "cart"; cart: Cart }
  | { type: "done"; conversation_id: string; duration_ms: number }
  | { type: "error"; code: string; message: string };

/**
 * Stream one chat turn.
 *
 * The browser's native EventSource is GET-only, so this reads the SSE frames off
 * a POST response body by hand (ADR-0003). Unknown event types are ignored so a
 * newer backend cannot break an older client.
 */
export async function streamChat(
  message: string,
  conversationId: string | null,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const open = () =>
    fetch(`${API_URL}/api/chat`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() },
      body: JSON.stringify({ message, conversation_id: conversationId }),
      signal,
    });

  let res = await open();
  if (res.status === 401 && (await refreshSession())) res = await open();

  if (!res.ok || !res.body) {
    const text = await res.text().catch(() => "");
    let code = "INTERNAL_ERROR";
    let msg = "Something went wrong.";
    try {
      const parsed = JSON.parse(text);
      code = parsed?.error?.code ?? code;
      msg = parsed?.error?.message ?? msg;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(code, msg, res.status);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    // Normalise line endings before anything else. The server sends CRLF, and
    // searching for "\n\n" in "\r\n\r\n" matches nothing: every frame arrives
    // and none is ever parsed, so the reply silently never appears.
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");

    // SSE frames are separated by a blank line.
    let split: number;
    while ((split = buffer.indexOf("\n\n")) !== -1) {
      emitFrame(buffer.slice(0, split), onEvent);
      buffer = buffer.slice(split + 2);
    }
  }

  // A trailing frame with no blank line after it still counts.
  if (buffer.trim()) emitFrame(buffer, onEvent);
}

function emitFrame(frame: string, onEvent: (event: ChatEvent) => void): void {
  let name = "message";
  const dataLines: string[] = [];

  for (const raw of frame.split("\n")) {
    const line = raw.replace(/\r$/, "");
    if (line.startsWith(":")) continue; // heartbeat comment
    if (line.startsWith("event:")) name = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (!dataLines.length) return;

  try {
    onEvent({ type: name, ...JSON.parse(dataLines.join("\n")) } as ChatEvent);
  } catch {
    /* a frame we cannot parse is skipped, never fatal */
  }
}
