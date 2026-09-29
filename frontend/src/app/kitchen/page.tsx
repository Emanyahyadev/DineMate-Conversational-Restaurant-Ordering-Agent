"use client";

import { useCallback, useEffect, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import {
  ArrowClockwiseIcon,
  PlusIcon,
  StarIcon,
  XIcon,
} from "@phosphor-icons/react/dist/ssr";

import AuthPanel from "@/components/AuthPanel";
import { useAuth } from "@/components/AuthProvider";
import * as api from "@/lib/api";

/**
 * The restaurant dashboard.
 *
 * A private portal for one authenticated restaurant: its orders, its menu, its
 * numbers. Every restaurant-specific value on this page comes from the signed-in
 * session via /api/kitchen/* — nothing about a particular restaurant is written
 * into this file, and no route it calls accepts a restaurant id.
 *
 * Design notes, since they are easy to undo by accident:
 *   - Warm ivory and charcoal (the `dash-*` tokens), scoped to this route.
 *   - Hierarchy comes from type, space and alignment. Colour is spent almost
 *     entirely on order state, which is the one thing that must read instantly.
 *   - A card is used only where it groups something. Metrics are not cards.
 */

const STATUS_LABEL: Record<string, string> = {
  confirmed: "New",
  preparing: "Preparing",
  ready: "Ready",
  out_for_delivery: "On its way",
  completed: "Completed",
  cancelled: "Cancelled",
};

/** Surface, text and dot per state, so the whole board reads at a glance. */
const STATUS_TONE: Record<string, string> = {
  confirmed: "bg-dash-new-soft text-dash-new",
  preparing: "bg-dash-cooking-soft text-dash-cooking",
  ready: "bg-dash-ready-soft text-dash-ready",
  out_for_delivery: "bg-dash-out-soft text-dash-out",
  completed: "bg-dash-new-soft text-dash-muted",
  cancelled: "bg-dash-danger-soft text-dash-danger",
};

const STATUS_DOT: Record<string, string> = {
  confirmed: "bg-dash-new",
  preparing: "bg-dash-cooking",
  ready: "bg-dash-ready",
  out_for_delivery: "bg-dash-out",
  completed: "bg-dash-muted",
  cancelled: "bg-dash-danger",
};

const ACTION_LABEL: Record<string, string> = {
  preparing: "Start cooking",
  ready: "Mark ready",
  out_for_delivery: "Send out",
  completed: "Handed over",
  cancelled: "Cancel",
};

/** The pass, left to right. This is the shape of a service, not a chart. */
const PIPELINE = ["confirmed", "preparing", "ready", "out_for_delivery"] as const;

const SECTIONS = ["Overview", "Orders", "Menu", "Restaurant"] as const;
type Section = (typeof SECTIONS)[number];

/** How often the board refreshes itself. A kitchen cannot be clicking refresh. */
const POLL_MS = 10_000;

/** Statuses the queue endpoint returns. Anything else has left the pass. */
const LIVE = new Set<string>(PIPELINE);

export default function KitchenPage() {
  const { user, loading, signOut } = useAuth();

  const [restaurant, setRestaurant] = useState<{
    id: string;
    name: string;
    cuisine: string;
  } | null>(null);
  const [staff, setStaff] = useState<{ email: string; name: string | null } | null>(null);
  const [orders, setOrders] = useState<api.KitchenOrder[]>([]);
  const [stats, setStats] = useState<api.KitchenStats | null>(null);
  const [menu, setMenu] = useState<api.KitchenMenuItem[]>([]);
  const [ratings, setRatings] = useState<{
    summary: api.RatingSummary;
    distribution: Record<string, number>;
    recent: api.Rating[];
  } | null>(null);
  const [section, setSection] = useState<Section>("Overview");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notStaff, setNotStaff] = useState(false);
  const [ready, setReady] = useState(false);

  /** A failure that is worth a word, versus one that just means signed out. */
  const note = useCallback((err: unknown) => {
    if (!(err instanceof api.ApiError)) return;
    if (err.status === 404) setNotStaff(true);
    else if (err.status !== 401) setError(err.message);
  }, []);

  /**
   * The board. This is the only thing that changes during a shift, so it is
   * the only thing that is polled - the previous version re-read the menu,
   * the ratings and the staff record every ten seconds and after every button
   * press, which is four round trips to a remote database for one number.
   */
  const loadOrders = useCallback(async () => {
    try {
      const live = await api.kitchenOrders();
      setOrders(live.items);
      setStats(live.stats);
      setNotStaff(false);
      setError(null);
    } catch (err) {
      note(err);
    } finally {
      setReady(true);
    }
  }, [note]);

  /**
   * Everything that is effectively fixed for the session. Fired together, but
   * each applied on its own: a slow ratings query must not hold up the name in
   * the header, which is what a single Promise.all was doing.
   */
  const loadContext = useCallback(() => {
    void api
      .kitchenMe()
      .then((me) => {
        setRestaurant(me.restaurant);
        setStaff(me.staff);
      })
      .catch(note);
    void api
      .kitchenMenu()
      .then((board) => setMenu(board.items))
      .catch(note);
    void api
      .kitchenRatings()
      .then(setRatings)
      .catch(note);
  }, [note]);

  useEffect(() => {
    if (!user) return;
    // Not a synchronous setState: each of these awaits its request first. The
    // lint rule cannot see through the async boundary.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadOrders();
    loadContext();

    // A backgrounded tab is a tab nobody is reading. Polling it burns the
    // connection pool and, on waking, shows a board up to ten seconds stale;
    // this refreshes on return instead.
    const tick = () => {
      if (document.visibilityState === "visible") void loadOrders();
    };
    const timer = setInterval(tick, POLL_MS);
    document.addEventListener("visibilitychange", tick);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", tick);
    };
  }, [user, loadOrders, loadContext]);

  async function advance(id: string, to: string) {
    setBusy(id);
    try {
      // The response is a full ticket, so the row it replaces is the only
      // thing that has to change. Reloading the board here cost a second
      // round trip during which every button on the page sat disabled.
      const { order } = await api.advanceOrder(id, to);
      setOrders((prev) =>
        LIVE.has(order.status)
          ? prev.map((o) => (o.id === order.id ? order : o))
          : prev.filter((o) => o.id !== order.id),
      );
      setError(null);
    } catch (err) {
      setError(err instanceof api.ApiError ? err.message : "That did not go through.");
    } finally {
      setBusy(null);
    }
  }

  function toggle(item: api.KitchenMenuItem) {
    const to = !item.is_available;
    // 86'ing a dish is a switch, and a switch that waits on a network is a
    // switch somebody presses twice. It flips now and puts itself back if the
    // server disagrees.
    setMenu((prev) => prev.map((i) => (i.id === item.id ? { ...i, is_available: to } : i)));
    void api.setItemAvailability(item.id, to).catch((err) => {
      setMenu((prev) =>
        prev.map((i) => (i.id === item.id ? { ...i, is_available: !to } : i)),
      );
      setError(
        err instanceof api.ApiError ? err.message : "That change did not save.",
      );
    });
  }

  if (loading) return <Splash>Loading…</Splash>;
  if (!user) return <AuthPanel initialAudience="restaurant" />;

  if (notStaff) {
    return (
      <Splash>
        <p className="text-[16px] font-medium tracking-tight text-dash-ink">
          This entrance is for restaurants.
        </p>
        <p className="mx-auto mt-1.5 max-w-xs text-[14px] leading-relaxed text-dash-muted">
          Your account is not attached to a restaurant.
        </p>
        <Link
          href="/"
          className="mt-6 inline-flex min-h-11 items-center rounded-lg bg-dash-accent px-5 text-[14px] font-medium text-white transition-colors hover:bg-dash-accent-hover"
        >
          Back to DineMate
        </Link>
      </Splash>
    );
  }

  const queued = orders.length;

  return (
    <div className="flex min-h-[100dvh] flex-col bg-dash-bg">
      <header className="sticky top-0 z-20 border-b border-dash-line bg-dash-surface/95 backdrop-blur">
        <div className="mx-auto flex w-full max-w-6xl items-center gap-3 px-5 py-3.5 lg:px-8">
          <Image
            src="/dinemate-mark.png"
            alt="DineMate"
            width={36}
            height={36}
            priority
            className="shrink-0 select-none"
          />
          <div className="min-w-0 flex-1">
            {restaurant ? (
              <h1 className="truncate text-[15.5px] font-semibold leading-tight tracking-tight text-dash-ink">
                {restaurant.name}
              </h1>
            ) : (
              /* A blank line reads as a broken header on a slow first load. */
              <span aria-hidden className="block h-4 w-40 animate-pulse rounded bg-dash-line" />
            )}
            <p className="mt-0.5 truncate text-[12.5px] leading-tight text-dash-muted">
              Restaurant dashboard
            </p>
          </div>

          <button
            type="button"
            onClick={() => void loadOrders()}
            aria-label="Refresh"
            title="Refresh"
            className="flex size-11 items-center justify-center rounded-lg text-dash-muted transition-colors hover:bg-dash-raised hover:text-dash-soft"
          >
            <ArrowClockwiseIcon size={16} />
          </button>
          <button
            type="button"
            onClick={() => void signOut()}
            className="min-h-11 rounded-lg px-3 text-[13.5px] text-dash-soft transition-colors hover:bg-dash-raised"
          >
            Sign out
          </button>
        </div>

        <nav
          aria-label="Dashboard sections"
          className="mx-auto flex w-full max-w-6xl gap-1 overflow-x-auto px-3 lg:px-6"
        >
          {SECTIONS.map((s) => {
            const active = section === s;
            return (
              <button
                key={s}
                type="button"
                onClick={() => setSection(s)}
                aria-current={active ? "page" : undefined}
                className={`relative flex min-h-11 shrink-0 items-center px-3 text-[13.5px] transition-colors ${
                  active
                    ? "font-medium text-dash-ink"
                    : "text-dash-muted hover:text-dash-soft"
                }`}
              >
                {s}
                {s === "Orders" && queued > 0 && (
                  <span className="ml-1.5 tabular-nums text-dash-muted">{queued}</span>
                )}
                <span
                  className={`absolute inset-x-3 -bottom-px h-px ${
                    active ? "bg-dash-ink" : "bg-transparent"
                  }`}
                />
              </button>
            );
          })}
        </nav>
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 px-5 py-8 lg:px-8">
        {error && <ErrorNote message={error} onRetry={() => void loadOrders()} />}

        {!ready ? (
          <Skeleton />
        ) : section === "Overview" ? (
          <Overview
            stats={stats}
            orders={orders}
            ratings={ratings}
            onOpenOrders={() => setSection("Orders")}
          />
        ) : section === "Orders" ? (
          <Orders
            orders={orders}
            busy={busy}
            onAdvance={(id, to) => void advance(id, to)}
          />
        ) : section === "Menu" ? (
          <MenuSection
            menu={menu}
            onToggle={toggle}
            onAdded={(item) => setMenu((prev) => [...prev, item])}
          />
        ) : (
          <RestaurantSection
            restaurant={restaurant}
            staff={staff}
            menu={menu}
            ratings={ratings}
          />
        )}
      </main>
    </div>
  );
}

/* ------------------------------------------------------------------ shared */

function Splash({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-[100dvh] items-center justify-center bg-dash-bg px-5 text-center">
      <div>{children}</div>
    </div>
  );
}

/** A quiet section heading. Type does the work, not a rule or a chip. */
function SectionHead({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="mb-4">
      <h2 className="text-[13px] font-medium uppercase tracking-[0.08em] text-dash-muted">
        {title}
      </h2>
      {hint && <p className="mt-1 text-[13.5px] text-dash-muted">{hint}</p>}
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-md px-2 py-1 text-[12px] font-medium ${
        STATUS_TONE[status] ?? "bg-dash-new-soft text-dash-soft"
      }`}
    >
      <span
        className={`size-1.5 rounded-full ${STATUS_DOT[status] ?? "bg-dash-muted"}`}
      />
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

/** Understated by design: a failure should inform, not alarm a busy kitchen. */
/** Five stars, filled to the score. Anything between is rounded to the nearest. */
function Stars({ value, size = 14 }: { value: number; size?: number }) {
  return (
    <span className="inline-flex items-center gap-0.5" aria-hidden>
      {[1, 2, 3, 4, 5].map((n) => (
        <StarIcon
          key={n}
          size={size}
          weight={n <= Math.round(value) ? "fill" : "regular"}
          className={n <= Math.round(value) ? "text-dash-cooking" : "text-dash-line-strong"}
        />
      ))}
    </span>
  );
}

function ErrorNote({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div
      role="alert"
      className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-dash-line bg-dash-danger-soft px-4 py-3"
    >
      <div>
        <p className="text-[13.5px] font-medium text-dash-danger">Something went wrong</p>
        <p className="mt-0.5 text-[13px] text-dash-soft">{message}</p>
      </div>
      <button
        type="button"
        onClick={onRetry}
        className="min-h-11 rounded-lg border border-dash-line-strong bg-dash-surface px-3.5 text-[13px] font-medium text-dash-soft transition-colors hover:bg-dash-raised"
      >
        Try again
      </button>
    </div>
  );
}

function EmptyState({ title, hint }: { title: string; hint: string }) {
  return (
    <div className="rounded-xl border border-dashed border-dash-line-strong px-6 py-16 text-center">
      <p className="text-[14.5px] font-medium text-dash-soft">{title}</p>
      <p className="mx-auto mt-1.5 max-w-xs text-[13.5px] leading-relaxed text-dash-muted">
        {hint}
      </p>
    </div>
  );
}

function Skeleton() {
  return (
    <div className="animate-pulse">
      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-dash-line bg-dash-line lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="bg-dash-surface px-5 py-6">
            <div className="h-2.5 w-20 rounded bg-dash-line" />
            <div className="mt-3 h-6 w-16 rounded bg-dash-line" />
          </div>
        ))}
      </div>
      <div className="mt-8 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-56 rounded-xl border border-dash-line bg-dash-surface" />
        ))}
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- overview */

function Overview({
  stats,
  orders,
  ratings,
  onOpenOrders,
}: {
  stats: api.KitchenStats | null;
  orders: api.KitchenOrder[];
  ratings: {
    summary: api.RatingSummary;
    distribution: Record<string, number>;
    recent: api.Rating[];
  } | null;
  onOpenOrders: () => void;
}) {
  // Counted from the tickets on screen rather than from `stats`. They are the
  // same rows, but a ticket moved a moment ago is already out of `orders` and
  // would still be in a `stats` figure fetched up to ten seconds earlier - so
  // the service line would disagree with the board directly beneath it.
  const live: Record<string, number> = {};
  for (const order of orders) live[order.status] = (live[order.status] ?? 0) + 1;
  const inQueue = orders.length;

  // The oldest ticket at each stage - the number a head chef actually watches.
  const oldestAt = (status: string) =>
    orders
      .filter((o) => o.status === status)
      .reduce((max, o) => Math.max(max, o.waiting_minutes), 0);

  const late = orders.filter((o) => o.is_late).length;

  return (
    <div className="flex flex-col gap-10">
      {/* The service line: the pass, left to right, showing what sits at each
          stage and how long the oldest has waited. It replaces a row of
          disconnected tiles with the one thing that governs a shift. */}
      <section>
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-[13px] font-medium uppercase tracking-[0.08em] text-dash-muted">
              Service line
            </h2>
            <p className="mt-1 text-[13.5px] text-dash-muted">
              {inQueue === 0
                ? "Nothing on the pass."
                : `${inQueue} ${inQueue === 1 ? "order" : "orders"} moving through the kitchen.`}
            </p>
          </div>
          {inQueue > 0 && (
            <button
              type="button"
              onClick={onOpenOrders}
              className="min-h-11 rounded-lg bg-dash-accent px-4 text-[13.5px] font-medium text-white transition-colors hover:bg-dash-accent-hover"
            >
              Open orders
            </button>
          )}
        </div>

        <ol className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-dash-line bg-dash-line lg:grid-cols-4">
          {PIPELINE.map((status) => {
            const count = live[status] ?? 0;
            const oldest = oldestAt(status);
            return (
              <li key={status} className="bg-dash-surface px-5 py-5">
                <div className="flex items-center gap-2">
                  <span className={`size-1.5 rounded-full ${STATUS_DOT[status]}`} />
                  <p className="text-[12.5px] text-dash-muted">{STATUS_LABEL[status]}</p>
                </div>
                <p
                  className={`mt-2 text-[30px] font-semibold leading-none tracking-tight tabular-nums ${
                    count > 0 ? "text-dash-ink" : "text-dash-line-strong"
                  }`}
                >
                  {count}
                </p>
                <p className="mt-2 h-4 text-[12px] text-dash-muted">
                  {count > 0 && `oldest ${oldest} min`}
                </p>
              </li>
            );
          })}
        </ol>

        {late > 0 && (
          <p className="mt-3 text-[13px] text-dash-danger">
            {late} {late === 1 ? "order has" : "orders have"} been waiting over 25 minutes.
          </p>
        )}
      </section>

      <div className="grid gap-10 lg:grid-cols-[1.15fr_1fr]">
        <section>
          <SectionHead title="Today" />
          <dl className="rounded-xl border border-dash-line bg-dash-surface">
            <TakingsRow label="Taken" value={stats?.revenue_today_display ?? "-"} emphasis />
            <TakingsRow label="Orders" value={stats ? String(stats.orders_today) : "-"} />
            <TakingsRow label="Cancelled" value={stats ? String(stats.cancelled_today) : "-"} />
          </dl>

          {stats && stats.top_items.length > 0 && (
            <>
              <div className="mt-8">
                <SectionHead title="Today&rsquo;s popular items" />
              </div>
              <ul className="rounded-xl border border-dash-line bg-dash-surface">
                {stats.top_items.map((item, i) => (
                  <li
                    key={item.name}
                    className={`flex items-baseline justify-between gap-4 px-5 py-3.5 ${
                      i > 0 ? "border-t border-dash-line" : ""
                    }`}
                  >
                    <span className="text-[14px] text-dash-ink">{item.name}</span>
                    <span className="shrink-0 text-[13.5px] tabular-nums text-dash-muted">
                      {item.quantity} {item.quantity === 1 ? "order" : "orders"}
                    </span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>

        <section>
          <SectionHead title="What guests said" />
          <GuestRatings ratings={ratings} />
        </section>
      </div>
    </div>
  );
}

function TakingsRow({
  label,
  value,
  emphasis,
}: {
  label: string;
  value: string;
  emphasis?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-dash-line px-5 py-4 last:border-0">
      <dt className="text-[13.5px] text-dash-muted">{label}</dt>
      <dd
        className={`tabular-nums tracking-tight text-dash-ink ${
          emphasis ? "text-[24px] font-semibold" : "text-[15px]"
        }`}
      >
        {value}
      </dd>
    </div>
  );
}

function GuestRatings({
  ratings,
}: {
  ratings: {
    summary: api.RatingSummary;
    distribution: Record<string, number>;
    recent: api.Rating[];
  } | null;
}) {
  if (!ratings || ratings.summary.count === 0) {
    return (
      <div className="rounded-xl border border-dashed border-dash-line-strong px-6 py-12 text-center">
        <p className="text-[14px] font-medium text-dash-soft">No ratings yet</p>
        <p className="mx-auto mt-1.5 max-w-[22rem] text-[13.5px] leading-relaxed text-dash-muted">
          Guests can rate an order once you have completed it. Their score appears here
          and beside your name on DineMate.
        </p>
      </div>
    );
  }

  const { average, count } = ratings.summary;
  const max = Math.max(...Object.values(ratings.distribution), 1);
  const withComments = ratings.recent.filter((r) => r.comment).slice(0, 4);

  return (
    <div className="rounded-xl border border-dash-line bg-dash-surface">
      <div className="flex items-center gap-6 border-b border-dash-line px-5 py-5">
        <div>
          <p className="text-[34px] font-semibold leading-none tracking-tight tabular-nums text-dash-ink">
            {average?.toFixed(1)}
          </p>
          <div className="mt-2">
            <Stars value={average ?? 0} />
          </div>
          <p className="mt-1.5 text-[12.5px] text-dash-muted">
            {count} {count === 1 ? "rating" : "ratings"}
          </p>
        </div>

        {/* The spread matters more than the mean: four fives and a one is a
            different kitchen from five threes. */}
        <div className="min-w-0 flex-1">
          {[5, 4, 3, 2, 1].map((star) => {
            const n = ratings.distribution[String(star)] ?? 0;
            return (
              <div key={star} className="flex items-center gap-2">
                <span className="w-2 text-[11.5px] tabular-nums text-dash-muted">{star}</span>
                <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-dash-raised">
                  <span
                    className="block h-full rounded-full bg-dash-cooking/60"
                    style={{ width: `${(n / max) * 100}%` }}
                  />
                </span>
                <span className="w-4 text-right text-[11.5px] tabular-nums text-dash-muted">
                  {n}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {withComments.length > 0 && (
        <ul>
          {withComments.map((r) => (
            <li key={r.id} className="border-b border-dash-line px-5 py-4 last:border-0">
              <div className="flex items-center gap-2">
                <Stars value={r.stars} size={12} />
                <span className="text-[12.5px] text-dash-muted">{r.customer}</span>
              </div>
              <p className="mt-1.5 text-[13.5px] leading-relaxed text-dash-ink">{r.comment}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ orders */

function Orders({
  orders,
  busy,
  onAdvance,
}: {
  orders: api.KitchenOrder[];
  busy: string | null;
  onAdvance: (id: string, to: string) => void;
}) {
  if (orders.length === 0) {
    return (
      <EmptyState
        title="No active orders"
        hint="New orders from DineMate will appear here. The board refreshes on its own."
      />
    );
  }

  return (
    <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      {orders.map((order) => (
        <OrderCard
          key={order.id}
          order={order}
          busy={busy === order.id}
          onAdvance={(to) => onAdvance(order.id, to)}
        />
      ))}
    </ul>
  );
}

function OrderCard({
  order,
  busy,
  onAdvance,
}: {
  order: api.KitchenOrder;
  busy: boolean;
  onAdvance: (to: string) => void;
}) {
  // The one place a card earns its keep: everything here belongs to one ticket.
  const advanceTo = order.next_statuses.filter((s) => s !== "cancelled");
  const canCancel = order.next_statuses.includes("cancelled");

  return (
    <li className="flex flex-col rounded-xl border border-dash-line bg-dash-surface">
      <div className="flex items-start justify-between gap-3 px-5 pt-5">
        <div className="min-w-0">
          <p className="text-[15px] font-semibold tracking-tight text-dash-ink">
            {order.id}
          </p>
          <p
            className={`mt-1 text-[12.5px] ${
              order.is_late ? "font-medium text-dash-danger" : "text-dash-muted"
            }`}
          >
            {order.waiting_minutes} min
            <span className="mx-1.5 text-dash-line-strong">·</span>
            <span className="capitalize">{order.fulfilment}</span>
          </p>
        </div>
        <StatusPill status={order.status} />
      </div>

      <ul className="flex flex-1 flex-col gap-2 px-5 py-5">
        {order.lines.map((line, i) => (
          <li key={i} className="flex items-baseline justify-between gap-3">
            <span className="text-[14px] leading-snug text-dash-ink">
              <span className="tabular-nums text-dash-muted">{line.quantity}×</span>{" "}
              {line.name}
            </span>
            <span className="shrink-0 text-[13.5px] tabular-nums text-dash-muted">
              {line.line_total_display}
            </span>
          </li>
        ))}
      </ul>

      {(order.contact_phone || order.delivery_address || order.notes) && (
        <dl className="mx-5 mb-5 flex flex-col gap-2.5 rounded-lg bg-dash-raised px-4 py-3.5 text-[13px]">
          {order.contact_phone && (
            <div>
              <dt className="text-[11.5px] uppercase tracking-[0.06em] text-dash-muted">
                Customer
              </dt>
              <dd className="mt-0.5 tabular-nums text-dash-ink">{order.contact_phone}</dd>
            </div>
          )}
          {order.fulfilment === "delivery" && order.delivery_address && (
            <div>
              <dt className="text-[11.5px] uppercase tracking-[0.06em] text-dash-muted">
                Deliver to
              </dt>
              <dd className="mt-0.5 leading-snug text-dash-ink">
                {order.delivery_address}
              </dd>
            </div>
          )}
          {order.notes && (
            <div>
              <dt className="text-[11.5px] uppercase tracking-[0.06em] text-dash-muted">
                Note
              </dt>
              <dd className="mt-0.5 leading-snug text-dash-ink">{order.notes}</dd>
            </div>
          )}
        </dl>
      )}

      <div className="mt-auto flex items-center justify-between gap-3 border-t border-dash-line px-5 py-4">
        <span className="text-[15px] font-semibold tabular-nums tracking-tight text-dash-ink">
          {order.total_display}
        </span>
        <div className="flex items-center gap-2">
          {canCancel && (
            <button
              type="button"
              onClick={() => onAdvance("cancelled")}
              disabled={busy}
              className="min-h-11 rounded-lg border border-dash-line-strong bg-dash-surface px-3.5 text-[13px] text-dash-soft transition-colors hover:border-dash-danger/40 hover:text-dash-danger disabled:opacity-45"
            >
              Cancel
            </button>
          )}
          {advanceTo.map((to) => (
            <button
              key={to}
              type="button"
              onClick={() => onAdvance(to)}
              disabled={busy}
              className="min-h-11 rounded-lg bg-dash-accent px-4 text-[13px] font-medium text-white transition-colors hover:bg-dash-accent-hover disabled:opacity-45"
            >
              {busy ? "…" : (ACTION_LABEL[to] ?? to)}
            </button>
          ))}
        </div>
      </div>
    </li>
  );
}

/* -------------------------------------------------------------------- menu */

function MenuSection({
  menu,
  onToggle,
  onAdded,
}: {
  menu: api.KitchenMenuItem[];
  onToggle: (item: api.KitchenMenuItem) => void;
  onAdded: (item: api.KitchenMenuItem) => void;
}) {
  const [adding, setAdding] = useState(false);

  const groups = new Map<string, api.KitchenMenuItem[]>();
  for (const item of menu) {
    const bucket = groups.get(item.category);
    if (bucket) bucket.push(item);
    else groups.set(item.category, [item]);
  }

  const off = menu.filter((i) => !i.is_available).length;

  return (
    <div className="flex max-w-3xl flex-col gap-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-[13px] font-medium uppercase tracking-[0.08em] text-dash-muted">
            Your menu
          </h2>
          <p className="mt-1 text-[13.5px] text-dash-muted">
            {menu.length} {menu.length === 1 ? "dish" : "dishes"}
            {off > 0 && `, ${off} currently off`}. DineMate stops offering a dish the moment
            you turn it off.
          </p>
        </div>
        {!adding && (
          <button
            type="button"
            onClick={() => setAdding(true)}
            className="inline-flex min-h-11 shrink-0 items-center gap-1.5 rounded-lg bg-dash-accent px-4 text-[13.5px] font-medium text-white transition-colors hover:bg-dash-accent-hover"
          >
            <PlusIcon size={15} weight="bold" />
            Add a dish
          </button>
        )}
      </div>

      {adding && (
        <AddDishForm
          onClose={() => setAdding(false)}
          onAdded={(item) => {
            setAdding(false);
            onAdded(item);
          }}
        />
      )}

      {menu.length === 0 && !adding ? (
        <EmptyState
          title="No dishes yet"
          hint="Add your first dish and DineMate will start offering it to guests."
        />
      ) : (
        [...groups.entries()].map(([category, items]) => (
          <section key={category}>
            <h3 className="mb-3 text-[12.5px] font-medium uppercase tracking-[0.08em] text-dash-muted">
              {category}
            </h3>
            <ul className="rounded-xl border border-dash-line bg-dash-surface">
              {items.map((item, i) => (
                <li
                  key={item.id}
                  className={`flex items-center gap-4 px-5 py-4 ${
                    i > 0 ? "border-t border-dash-line" : ""
                  }`}
                >
                  <span className="min-w-0 flex-1">
                    <span
                      className={`block truncate text-[14.5px] ${
                        item.is_available ? "text-dash-ink" : "text-dash-muted"
                      }`}
                    >
                      {item.name}
                    </span>
                    {item.description && (
                      <span className="mt-0.5 block truncate text-[12.5px] text-dash-muted">
                        {item.description}
                      </span>
                    )}
                    {!item.is_available && (
                      <span className="mt-0.5 block text-[12.5px] text-dash-danger">
                        Off the menu
                      </span>
                    )}
                  </span>
                  <span className="w-24 shrink-0 text-right text-[14px] tabular-nums text-dash-soft">
                    {item.price_display}
                  </span>
                  <button
                    type="button"
                    onClick={() => onToggle(item)}
                    aria-pressed={!item.is_available}
                    className={`min-h-11 w-[104px] shrink-0 rounded-lg border px-3 text-[13px] font-medium transition-colors ${
                      item.is_available
                        ? "border-dash-line-strong bg-dash-surface text-dash-soft hover:border-dash-danger/40 hover:text-dash-danger"
                        : "border-transparent bg-dash-accent text-white hover:bg-dash-accent-hover"
                    }`}
                  >
                    {item.is_available ? "Turn off" : "Turn on"}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ))
      )}
    </div>
  );
}

const FIELD =
  "w-full rounded-lg border border-dash-line-strong bg-dash-bg px-3.5 py-2.5 text-[15px] text-dash-ink outline-none transition-colors placeholder:text-dash-muted focus:border-dash-accent focus:bg-dash-surface";

/**
 * The courses and tags a dish may carry. They are a server rule (a CHECK
 * constraint) rather than a list duplicated here where it could drift, but they
 * do not change within a session - so they are fetched once and the form opens
 * instantly every time after that.
 */
let optionsCache: { items: string[]; dietary_tags: string[] } | null = null;

function AddDishForm({
  onClose,
  onAdded,
}: {
  onClose: () => void;
  onAdded: (item: api.KitchenMenuItem) => void;
}) {
  const [categories, setCategories] = useState<string[]>(optionsCache?.items ?? []);
  const [tags, setTags] = useState<string[]>(optionsCache?.dietary_tags ?? []);
  const [form, setForm] = useState({ name: "", category: "", price: "", description: "" });
  const [chosen, setChosen] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (optionsCache) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setForm((f) => (f.category ? f : { ...f, category: optionsCache!.items[0] ?? "" }));
      return;
    }
    api
      .menuCategories()
      .then((r) => {
        optionsCache = r;
        setCategories(r.items);
        setTags(r.dietary_tags);
        setForm((f) => (f.category ? f : { ...f, category: r.items[0] ?? "" }));
      })
      .catch(() => setError("Could not load the courses."));
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const { item } = await api.addDish({
        name: form.name.trim(),
        category: form.category,
        price: form.price.trim(),
        description: form.description.trim(),
        dietary_tags: chosen,
      });
      // The new dish is in the response, so the board does not have to be
      // re-read to show it.
      onAdded(item);
    } catch (err) {
      setError(err instanceof api.ApiError ? err.message : "Could not add that dish.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="rounded-xl border border-dash-line bg-dash-surface p-6">
      <div className="mb-5 flex items-start justify-between gap-3">
        <div>
          <h3 className="text-[15px] font-semibold tracking-tight text-dash-ink">Add a dish</h3>
          <p className="mt-0.5 text-[13px] text-dash-muted">
            It goes on your menu straight away, and DineMate starts offering it.
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="flex size-9 shrink-0 items-center justify-center rounded-lg text-dash-muted transition-colors hover:bg-dash-raised"
        >
          <XIcon size={16} />
        </button>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <label htmlFor="d-name" className="mb-1.5 block text-[13px] font-medium text-dash-soft">
            Dish name
          </label>
          <input
            id="d-name"
            required
            autoFocus
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="Chicken Karahi"
            className={FIELD}
          />
        </div>

        <div>
          <label
            htmlFor="d-category"
            className="mb-1.5 block text-[13px] font-medium text-dash-soft"
          >
            Course
          </label>
          <select
            id="d-category"
            required
            value={form.category}
            onChange={(e) => setForm({ ...form, category: e.target.value })}
            className={FIELD}
          >
            {categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label htmlFor="d-price" className="mb-1.5 block text-[13px] font-medium text-dash-soft">
            Price
          </label>
          <input
            id="d-price"
            required
            inputMode="numeric"
            value={form.price}
            onChange={(e) => setForm({ ...form, price: e.target.value })}
            placeholder="1650"
            className={FIELD}
          />
        </div>

        <div className="sm:col-span-2">
          <label
            htmlFor="d-description"
            className="mb-1.5 block text-[13px] font-medium text-dash-soft"
          >
            Description <span className="text-dash-muted">(optional)</span>
          </label>
          <textarea
            id="d-description"
            rows={2}
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            placeholder="Cooked on the tawa with tomato, ginger and green chilli."
            className={`${FIELD} resize-none`}
          />
        </div>

        {tags.length > 0 && (
          <div className="sm:col-span-2">
            <p className="mb-2 text-[13px] font-medium text-dash-soft">
              Tags <span className="text-dash-muted">(optional)</span>
            </p>
            <div className="flex flex-wrap gap-2">
              {tags.map((tag) => {
                const on = chosen.includes(tag);
                return (
                  <button
                    key={tag}
                    type="button"
                    // The updater form, not `chosen` from this render: two
                    // taps in quick succession batch, and the second would
                    // otherwise overwrite the first.
                    onClick={() =>
                      setChosen((prev) =>
                        prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag],
                      )
                    }
                    aria-pressed={on}
                    className={`min-h-11 rounded-lg border px-3 text-[13px] capitalize transition-colors ${
                      on
                        ? "border-dash-accent bg-dash-accent text-white"
                        : "border-dash-line-strong text-dash-soft hover:bg-dash-raised"
                    }`}
                  >
                    {tag.replace("_", " ")}
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>

      {error && (
        <div role="alert" className="mt-4 rounded-lg bg-dash-danger-soft px-3.5 py-3">
          <p className="text-[13px] font-medium text-dash-danger">Could not add it</p>
          <p className="mt-0.5 text-[13px] leading-snug text-dash-soft">{error}</p>
        </div>
      )}

      <p className="mt-4 text-[12.5px] leading-relaxed text-dash-muted">
        Allergens are not recorded here, so DineMate tells guests the allergen information
        for this dish has not been checked.
      </p>

      <div className="mt-5 flex justify-end gap-2">
        <button
          type="button"
          onClick={onClose}
          className="min-h-11 rounded-lg border border-dash-line-strong bg-dash-surface px-4 text-[13.5px] text-dash-soft transition-colors hover:bg-dash-raised"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={busy}
          className="min-h-11 rounded-lg bg-dash-accent px-5 text-[13.5px] font-medium text-white transition-colors hover:bg-dash-accent-hover disabled:opacity-50"
        >
          {busy ? "Adding…" : "Add to menu"}
        </button>
      </div>
    </form>
  );
}

/* -------------------------------------------------------------- restaurant */

function RestaurantSection({
  restaurant,
  staff,
  menu,
  ratings,
}: {
  restaurant: { id: string; name: string; cuisine: string } | null;
  staff: { email: string; name: string | null } | null;
  menu: api.KitchenMenuItem[];
  ratings: { summary: api.RatingSummary } | null;
}) {
  // Only fields the application actually holds. Opening hours, address and a
  // contact number are not part of a restaurant record today, so they are not
  // shown as blanks waiting to be filled.
  const rows = [
    { label: "Restaurant", value: restaurant?.name },
    { label: "Cuisine", value: restaurant?.cuisine },
    { label: "Dishes on the menu", value: menu.length ? String(menu.length) : undefined },
    {
      label: "Currently available",
      value: menu.length
        ? `${menu.filter((i) => i.is_available).length} of ${menu.length}`
        : undefined,
    },
    {
      label: "Guest rating",
      value:
        ratings && ratings.summary.count > 0
          ? ratings.summary.average?.toFixed(1) +
            " from " +
            ratings.summary.count +
            (ratings.summary.count === 1 ? " rating" : " ratings")
          : "Not rated yet",
    },
  ].filter((r) => r.value);

  const account = [
    { label: "Signed in as", value: staff?.name || staff?.email },
    { label: "Email", value: staff?.email },
  ].filter((r) => r.value);

  return (
    <div className="flex max-w-2xl flex-col gap-10">
      <section>
        <SectionHead title="Restaurant" />
        <DetailList rows={rows} />
      </section>

      <section>
        <SectionHead title="Account" />
        <DetailList rows={account} />
      </section>
    </div>
  );
}

function DetailList({ rows }: { rows: { label: string; value?: string }[] }) {
  return (
    <dl className="rounded-xl border border-dash-line bg-dash-surface">
      {rows.map((row, i) => (
        <div
          key={row.label}
          className={`flex flex-wrap items-baseline gap-x-6 gap-y-1 px-5 py-4 ${
            i > 0 ? "border-t border-dash-line" : ""
          }`}
        >
          <dt className="w-44 shrink-0 text-[13.5px] text-dash-muted">{row.label}</dt>
          <dd className="text-[14.5px] text-dash-ink">{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}
