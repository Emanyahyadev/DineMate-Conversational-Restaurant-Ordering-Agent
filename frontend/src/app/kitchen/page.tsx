"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ArrowClockwiseIcon,
  CheckCircleIcon,
  ClockIcon,
  ForkKnifeIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react/dist/ssr";

import BrandMark from "@/components/BrandMark";
import { useAuth } from "@/components/AuthProvider";
import * as api from "@/lib/api";

const STATUS_LABEL: Record<string, string> = {
  confirmed: "New",
  preparing: "Cooking",
  ready: "Ready",
  out_for_delivery: "Out",
  completed: "Done",
  cancelled: "Cancelled",
};

const ACTION_LABEL: Record<string, string> = {
  preparing: "Start cooking",
  ready: "Mark ready",
  out_for_delivery: "Send out",
  completed: "Handed over",
  cancelled: "Cancel",
};

/** How often the board refreshes itself. A kitchen cannot be clicking refresh. */
const POLL_MS = 10_000;

export default function KitchenPage() {
  const { user, loading, signIn, signOut } = useAuth();

  const [restaurant, setRestaurant] = useState<{ name: string; cuisine: string } | null>(
    null,
  );
  const [orders, setOrders] = useState<api.KitchenOrder[]>([]);
  const [stats, setStats] = useState<api.KitchenStats | null>(null);
  const [menu, setMenu] = useState<api.KitchenMenuItem[]>([]);
  const [tab, setTab] = useState<"orders" | "menu">("orders");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notStaff, setNotStaff] = useState(false);

  const load = useCallback(async () => {
    try {
      const [me, live, board] = await Promise.all([
        api.kitchenMe(),
        api.kitchenOrders(),
        api.kitchenMenu(),
      ]);
      setRestaurant(me.restaurant);
      setOrders(live.items);
      setStats(live.stats);
      setMenu(board.items);
      setNotStaff(false);
      setError(null);
    } catch (err) {
      if (err instanceof api.ApiError && err.status === 404) setNotStaff(true);
      else if (err instanceof api.ApiError && err.status !== 401) setError(err.message);
    }
  }, []);

  useEffect(() => {
    if (!user) return;
    void load();
    const t = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(t);
  }, [user, load]);

  async function advance(id: string, to: string) {
    setBusy(id);
    try {
      await api.advanceOrder(id, to);
      await load();
    } catch (err) {
      setError(err instanceof api.ApiError ? err.message : "That did not go through.");
    } finally {
      setBusy(null);
    }
  }

  async function toggle(item: api.KitchenMenuItem) {
    setBusy(item.id);
    try {
      await api.setItemAvailability(item.id, !item.is_available);
      await load();
    } finally {
      setBusy(null);
    }
  }

  if (loading) {
    return <Centered>Loading…</Centered>;
  }

  if (!user) {
    return <StaffSignIn onSignIn={signIn} />;
  }

  if (notStaff) {
    return (
      <Centered>
        <p className="text-[15px] font-medium text-ink">This is the kitchen entrance.</p>
        <p className="mt-1 text-[13.5px] text-ink-muted">
          Your account is not attached to a restaurant.
        </p>
        <a
          href="/"
          className="mt-4 inline-block rounded-full bg-accent px-5 py-2.5 text-[14px] font-medium text-white"
        >
          Back to DineMate
        </a>
      </Centered>
    );
  }

  return (
    <div className="flex min-h-[100dvh] flex-col bg-canvas">
      <header className="sticky top-0 z-20 shrink-0 border-b border-line bg-surface">
        <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-3 lg:px-6">
          <BrandMark size={34} priority />
          <div className="min-w-0 flex-1">
            <p className="truncate text-[15px] font-semibold tracking-tight text-ink">
              {restaurant?.name ?? "Kitchen"}
            </p>
            <p className="truncate text-[12.5px] text-ink-muted">
              {restaurant?.cuisine} · kitchen display
            </p>
          </div>
          <button
            type="button"
            onClick={() => void load()}
            aria-label="Refresh now"
            className="flex size-11 items-center justify-center rounded-full text-ink-soft hover:bg-canvas"
          >
            <ArrowClockwiseIcon size={17} />
          </button>
          <button
            type="button"
            onClick={() => void signOut()}
            className="min-h-11 rounded-full border border-line-strong px-3.5 text-[13.5px] text-ink-soft hover:bg-canvas"
          >
            Sign out
          </button>
        </div>

        <div className="mx-auto flex max-w-6xl gap-1 px-4 pb-2 lg:px-6">
          {(["orders", "menu"] as const).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTab(t)}
              aria-pressed={tab === t}
              className={`min-h-11 rounded-full px-4 text-[13.5px] font-medium transition-colors ${
                tab === t ? "bg-accent text-white" : "text-ink-soft hover:bg-canvas"
              }`}
            >
              {t === "orders" ? `Orders (${orders.length})` : "Menu"}
            </button>
          ))}
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-5 lg:px-6">
        {error && (
          <p role="alert" className="mb-4 rounded-2xl bg-danger-soft px-4 py-3 text-[13.5px] text-danger">
            {error}
          </p>
        )}

        {tab === "orders" ? (
          <>
            {stats && <Stats stats={stats} />}
            {orders.length === 0 ? (
              <div className="rounded-2xl border border-line bg-surface px-5 py-12 text-center">
                <CheckCircleIcon size={28} className="mx-auto text-ink-muted" />
                <p className="mt-2 text-[14px] text-ink-soft">
                  Nothing in the queue. The board refreshes on its own.
                </p>
              </div>
            ) : (
              <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {orders.map((order) => (
                  <Ticket
                    key={order.id}
                    order={order}
                    busy={busy === order.id}
                    onAdvance={(to) => void advance(order.id, to)}
                  />
                ))}
              </ul>
            )}
          </>
        ) : (
          <MenuBoard menu={menu} busy={busy} onToggle={(i) => void toggle(i)} />
        )}
      </main>
    </div>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-[100dvh] items-center justify-center bg-canvas px-4 text-center">
      <div>{children}</div>
    </div>
  );
}

function Stats({ stats }: { stats: api.KitchenStats }) {
  const tiles = [
    { label: "Orders today", value: String(stats.orders_today) },
    { label: "Revenue today", value: stats.revenue_today_display },
    { label: "In the queue", value: String(Object.values(stats.live_by_status).reduce((a, b) => a + b, 0)) },
    { label: "Cancelled", value: String(stats.cancelled_today) },
  ];
  return (
    <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
      {tiles.map((t) => (
        <div key={t.label} className="rounded-2xl border border-line bg-surface px-4 py-3">
          <p className="text-[12.5px] text-ink-muted">{t.label}</p>
          <p className="mt-0.5 text-[19px] font-semibold tabular-nums tracking-tight text-ink">
            {t.value}
          </p>
        </div>
      ))}
      {stats.top_items.length > 0 && (
        <div className="col-span-2 rounded-2xl border border-line bg-surface px-4 py-3 lg:col-span-4">
          <p className="text-[12.5px] text-ink-muted">Going out most today</p>
          <p className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-[13.5px] text-ink">
            {stats.top_items.map((i) => (
              <span key={i.name}>
                <span className="tabular-nums font-medium">{i.quantity}×</span> {i.name}
              </span>
            ))}
          </p>
        </div>
      )}
    </div>
  );
}

function Ticket({
  order,
  busy,
  onAdvance,
}: {
  order: api.KitchenOrder;
  busy: boolean;
  onAdvance: (to: string) => void;
}) {
  return (
    <li
      className={`flex flex-col rounded-2xl border bg-surface p-4 ${
        order.is_late ? "border-danger/40" : "border-line"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[14.5px] font-semibold tracking-tight text-ink">{order.id}</p>
          <p
            className={`flex items-center gap-1 text-[12.5px] ${
              order.is_late ? "font-medium text-danger" : "text-ink-muted"
            }`}
          >
            <ClockIcon size={13} />
            {order.waiting_minutes} min · {order.fulfilment}
          </p>
        </div>
        <span className="shrink-0 rounded-full bg-accent-soft px-2.5 py-1 text-[12px] font-medium text-accent">
          {STATUS_LABEL[order.status] ?? order.status}
        </span>
      </div>

      <ul className="my-3 flex flex-1 flex-col gap-1">
        {order.lines.map((line, i) => (
          <li key={i} className="flex justify-between gap-3 text-[13.5px] text-ink">
            <span>
              <span className="font-semibold tabular-nums">{line.quantity}×</span>{" "}
              {line.name}
            </span>
            <span className="shrink-0 tabular-nums text-ink-muted">
              {line.line_total_display}
            </span>
          </li>
        ))}
      </ul>

      {order.notes && (
        <p className="mb-3 rounded-2xl bg-canvas px-3 py-2 text-[12.5px] text-ink-soft">
          {order.notes}
        </p>
      )}

      <div className="flex items-center justify-between gap-2 border-t border-line pt-3">
        <span className="text-[14px] font-semibold tabular-nums text-ink">
          {order.total_display}
        </span>
        <div className="flex gap-1.5">
          {order.next_statuses.map((to) => (
            <button
              key={to}
              type="button"
              onClick={() => onAdvance(to)}
              disabled={busy}
              className={`min-h-11 rounded-full px-3.5 text-[13px] font-medium transition-colors disabled:opacity-45 ${
                to === "cancelled"
                  ? "border border-line-strong text-ink-soft hover:border-danger hover:text-danger"
                  : "bg-accent text-white hover:bg-accent-hover"
              }`}
            >
              {ACTION_LABEL[to] ?? to}
            </button>
          ))}
        </div>
      </div>
    </li>
  );
}

function MenuBoard({
  menu,
  busy,
  onToggle,
}: {
  menu: api.KitchenMenuItem[];
  busy: string | null;
  onToggle: (item: api.KitchenMenuItem) => void;
}) {
  const groups = new Map<string, api.KitchenMenuItem[]>();
  for (const item of menu) {
    const bucket = groups.get(item.category);
    if (bucket) bucket.push(item);
    else groups.set(item.category, [item]);
  }

  return (
    <div className="rounded-2xl border border-line bg-surface">
      <div className="border-b border-line px-5 py-3.5">
        <h2 className="text-[15px] font-semibold tracking-tight text-ink">
          Today&rsquo;s availability
        </h2>
        <p className="mt-0.5 text-[13px] text-ink-muted">
          Turn a dish off and DineMate stops offering it immediately.
        </p>
      </div>

      {[...groups.entries()].map(([category, items]) => (
        <section key={category}>
          <h3 className="flex items-center gap-2 border-b border-line bg-canvas px-5 py-1.5 text-[12px] font-semibold uppercase tracking-wide text-ink-muted">
            <ForkKnifeIcon size={13} />
            {category}
          </h3>
          <ul>
            {items.map((item) => (
              <li
                key={item.id}
                className="flex items-center gap-3 border-b border-line/60 px-5 py-2.5 last:border-0"
              >
                <span className="min-w-0 flex-1">
                  <span
                    className={`block text-[14px] ${
                      item.is_available ? "text-ink" : "text-ink-muted line-through"
                    }`}
                  >
                    {item.name}
                  </span>
                </span>
                <span className="shrink-0 text-[13px] tabular-nums text-ink-soft">
                  {item.price_display}
                </span>
                <button
                  type="button"
                  onClick={() => onToggle(item)}
                  disabled={busy === item.id}
                  aria-pressed={!item.is_available}
                  className={`min-h-11 shrink-0 rounded-full px-3.5 text-[13px] font-medium transition-colors disabled:opacity-45 ${
                    item.is_available
                      ? "border border-line-strong text-ink-soft hover:border-danger hover:text-danger"
                      : "bg-danger-soft text-danger"
                  }`}
                >
                  {item.is_available ? "86 it" : "Sold out"}
                </button>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

function StaffSignIn({
  onSignIn,
}: {
  onSignIn: (email: string, password: string) => Promise<void>;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await onSignIn(email.trim(), password);
    } catch (err) {
      setError(err instanceof api.ApiError ? err.message : "Could not sign you in.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-[100dvh] items-center justify-center bg-canvas px-4">
      <form
        onSubmit={submit}
        className="w-full max-w-sm rounded-2xl border border-line bg-surface p-5"
      >
        <div className="mb-4 flex items-center gap-2.5">
          <BrandMark size={36} priority />
          <div>
            <p className="text-[15px] font-semibold tracking-tight text-ink">
              Kitchen display
            </p>
            <p className="text-[13px] text-ink-muted">Staff sign in</p>
          </div>
        </div>

        <label htmlFor="k-email" className="mb-1 block text-[13.5px] text-ink-soft">
          Email
        </label>
        <input
          id="k-email"
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoComplete="email"
          className="mb-3 w-full rounded-2xl border border-line-strong bg-surface px-3.5 py-3 text-[16px] text-ink outline-none focus:border-accent"
        />

        <label htmlFor="k-password" className="mb-1 block text-[13.5px] text-ink-soft">
          Password
        </label>
        <input
          id="k-password"
          type="password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
          className="w-full rounded-2xl border border-line-strong bg-surface px-3.5 py-3 text-[16px] text-ink outline-none focus:border-accent"
        />

        {error && (
          <p role="alert" className="mt-3 rounded-2xl bg-danger-soft px-3.5 py-2.5 text-[13.5px] text-danger">
            <WarningCircleIcon size={15} className="mr-1 inline" />
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={busy}
          className="mt-4 w-full rounded-full bg-accent px-4 py-3 text-[14.5px] font-medium text-white hover:bg-accent-hover disabled:opacity-45"
        >
          {busy ? "One moment…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
