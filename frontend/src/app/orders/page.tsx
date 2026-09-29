"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeftIcon, StarIcon, WarningCircleIcon } from "@phosphor-icons/react/dist/ssr";

import AuthGate from "@/components/AuthGate";
import SiteHeader from "@/components/SiteHeader";
import * as api from "@/lib/api";

const STATUS_LABEL: Record<string, string> = {
  confirmed: "Confirmed",
  preparing: "Being prepared",
  ready: "Ready",
  out_for_delivery: "On its way",
  completed: "Completed",
  cancelled: "Cancelled",
};

/** The journey a ticket takes, in the order the kitchen marks it. */
const PICKUP_TRACK = ["confirmed", "preparing", "ready", "completed"] as const;
const DELIVERY_TRACK = [
  "confirmed",
  "preparing",
  "ready",
  "out_for_delivery",
  "completed",
] as const;

const SETTLED = new Set(["completed", "cancelled"]);

/** How often to ask the kitchen for news while an order is still live. */
const POLL_MS = 8000;

function OrderList() {
  const [orders, setOrders] = useState<api.Order[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  // The clock as of the last poll. Held in state so that "can this still be
  // cancelled?" is answered by a value React knows about, rather than by
  // reading the real clock while rendering.
  const [now, setNow] = useState(() => Date.now());

  const load = useCallback(async () => {
    try {
      const items = (await api.listOrders()).items;
      setOrders(items);
      setNow(Date.now());
      setError(null);
    } catch (err) {
      setError(err instanceof api.ApiError ? err.message : "Could not load your orders.");
    }
  }, []);

  useEffect(() => {
    // Not a synchronous setState: `load` awaits the request first. The lint
    // rule cannot see through the async boundary.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  // The chef marking a ticket "ready" is news the customer is waiting on, so
  // this page follows the kitchen rather than showing whatever was true when it
  // was opened. Polling stops once nothing is live and while the tab is hidden,
  // so a forgotten tab is not a standing load on Neon.
  const live = orders?.some((o) => !SETTLED.has(o.status)) ?? false;

  useEffect(() => {
    if (!live) return;

    const tick = () => {
      if (document.visibilityState === "visible") void load();
    };
    const timer = window.setInterval(tick, POLL_MS);
    // Coming back to the tab should show current state at once, not in 8s.
    document.addEventListener("visibilitychange", tick);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", tick);
    };
  }, [live, load]);

  async function cancel(id: string) {
    setBusyId(id);
    try {
      await api.cancelOrder(id);
      await load();
    } catch (err) {
      setError(err instanceof api.ApiError ? err.message : "Could not cancel that.");
    } finally {
      setBusyId(null);
    }
  }

  if (error) {
    return (
      <div role="alert" className="rounded-2xl bg-danger-soft px-4 py-3.5">
        <p className="flex items-start gap-2 text-[13.5px] text-danger">
          <WarningCircleIcon size={17} className="mt-px shrink-0" />
          {error}
        </p>
        <button
          type="button"
          onClick={() => void load()}
          className="mt-3 rounded-full border border-danger/30 px-3.5 py-1.5 text-[13.5px] font-medium text-danger hover:bg-danger/10"
        >
          Try again
        </button>
      </div>
    );
  }

  if (orders === null) {
    return (
      <ul className="flex flex-col gap-3">
        {[0, 1].map((i) => (
          <li key={i} className="h-28 animate-pulse rounded-2xl border border-line bg-surface" />
        ))}
      </ul>
    );
  }

  if (orders.length === 0) {
    return (
      <div className="rounded-2xl border border-line bg-surface px-5 py-10 text-center">
        <p className="text-[14px] text-ink-muted">You have not ordered anything yet.</p>
        <Link
          href="/"
          className="mt-4 inline-block rounded-full bg-accent px-5 py-2.5 text-[14px] font-medium text-white hover:bg-accent-hover"
        >
          Start an order
        </Link>
      </div>
    );
  }

  return (
    <ul className="flex flex-col gap-3">
      {orders.map((order) => {
        // Compared against the clock captured at the last poll, not Date.now()
        // read during render: rendering has to be pure, and reading the real
        // clock here meant the Cancel button stayed on screen after the window
        // closed, because nothing re-rendered when it passed.
        const cancellable =
          order.status === "confirmed" &&
          new Date(order.cancellable_until).getTime() > now;

        return (
          <li key={order.id} className="rounded-2xl border border-line bg-surface p-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <div className="min-w-0">
                <p className="text-[14.5px] font-semibold tracking-tight text-ink">
                  {order.restaurant_name || order.id}
                </p>
                {order.restaurant_name && (
                  <p className="text-[12.5px] text-ink-muted">{order.id}</p>
                )}
              </div>
              <span
                className={`rounded-full px-2.5 py-1 text-[12.5px] font-medium ${
                  order.status === "cancelled"
                    ? "bg-danger-soft text-danger"
                    : "bg-accent-soft text-accent"
                }`}
              >
                {STATUS_LABEL[order.status] ?? order.status}
              </span>
            </div>

            {order.status !== "cancelled" && <StatusTrack order={order} />}

            <ul className="mt-2 flex flex-col gap-0.5">
              {order.lines.map((line, i) => (
                <li key={i} className="flex justify-between gap-3 text-[13.5px] text-ink-soft">
                  <span>
                    <span className="tabular-nums">{line.quantity}×</span> {line.name}
                  </span>
                  <span className="tabular-nums">{line.line_total_display}</span>
                </li>
              ))}
            </ul>

            <div className="mt-3 flex items-center justify-between gap-3 border-t border-line pt-3">
              <p className="text-[14.5px] font-semibold tabular-nums text-ink">
                {order.total_display}
              </p>
              {cancellable && (
                <button
                  type="button"
                  onClick={() => void cancel(order.id)}
                  disabled={busyId === order.id}
                  className="min-h-11 rounded-full border border-line-strong px-3.5 text-[13.5px] text-ink-soft transition-colors hover:border-danger hover:bg-danger-soft hover:text-danger disabled:opacity-45"
                >
                  {busyId === order.id ? "Cancelling…" : "Cancel"}
                </button>
              )}
            </div>

            {(order.can_rate || order.rating) && (
              <RateOrder
                order={order}
                onRated={() => void load()}
                onError={(m) => setError(m)}
              />
            )}
          </li>
        );
      })}
    </ul>
  );
}

/**
 * Where the order has got to, as the kitchen marked it.
 *
 * The steps are the real state machine, so what the customer reads here and
 * what the chef pressed on the dashboard are the same thing said twice.
 */
function StatusTrack({ order }: { order: api.Order }) {
  const track: readonly string[] =
    order.fulfilment === "delivery" ? DELIVERY_TRACK : PICKUP_TRACK;
  const reached = track.indexOf(order.status);

  return (
    <ol
      aria-label="Order progress"
      className="mt-3 flex items-center gap-1.5 overflow-x-auto"
    >
      {track.map((step, i) => {
        const done = i <= reached;
        const current = i === reached;
        return (
          <li key={step} className="flex min-w-0 flex-1 items-center gap-1.5">
            <div className="min-w-0 flex-1">
              <div
                className={`h-1 rounded-full transition-colors ${
                  done ? "bg-accent" : "bg-line"
                }`}
              />
              <p
                className={`mt-1 truncate text-[11.5px] ${
                  current ? "font-medium text-accent" : "text-ink-muted"
                }`}
              >
                {STATUS_LABEL[step]}
              </p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

/**
 * Rating a finished order.
 *
 * Offered only where the server said `can_rate`, which means this customer's
 * own order and only once it has actually been completed — so a score always
 * comes from somebody who ate the food.
 */
function RateOrder({
  order,
  onRated,
  onError,
}: {
  order: api.Order;
  onRated: () => void;
  onError: (message: string) => void;
}) {
  const [stars, setStars] = useState(0);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);

  if (order.rating) {
    return (
      <div className="mt-3 flex items-center gap-2 border-t border-line pt-3">
        <StarRow value={order.rating.stars} />
        <p className="text-[13px] text-ink-muted">
          {order.rating.comment ? order.rating.comment : "Thanks for rating this."}
        </p>
      </div>
    );
  }

  async function submit() {
    if (!stars || busy) return;
    setBusy(true);
    try {
      await api.rateOrder(order.id, stars, comment.trim());
      onRated();
    } catch (err) {
      onError(err instanceof api.ApiError ? err.message : "Could not save that rating.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-3 border-t border-line pt-3">
      <p className="text-[13px] text-ink-soft">How was it?</p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <div className="flex">
          {[1, 2, 3, 4, 5].map((n) => (
            <button
              key={n}
              type="button"
              onClick={() => setStars(n)}
              aria-label={`${n} ${n === 1 ? "star" : "stars"}`}
              aria-pressed={stars === n}
              className="flex size-11 items-center justify-center"
            >
              <StarIcon
                size={22}
                weight={n <= stars ? "fill" : "regular"}
                className={n <= stars ? "text-amber-500" : "text-line-strong"}
              />
            </button>
          ))}
        </div>
        {stars > 0 && (
          <>
            <input
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="Anything to add? (optional)"
              maxLength={500}
              className="min-w-0 flex-1 rounded-2xl border border-line-strong bg-surface px-3.5 py-2.5 text-[14px] text-ink outline-none focus:border-accent"
            />
            <button
              type="button"
              onClick={() => void submit()}
              disabled={busy}
              className="min-h-11 rounded-full bg-accent px-4 text-[13.5px] font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-45"
            >
              {busy ? "Sending…" : "Send"}
            </button>
          </>
        )}
      </div>
    </div>
  );
}

function StarRow({ value }: { value: number }) {
  return (
    <span className="inline-flex shrink-0 items-center gap-0.5" aria-label={`${value} of 5`}>
      {[1, 2, 3, 4, 5].map((n) => (
        <StarIcon
          key={n}
          size={14}
          weight={n <= value ? "fill" : "regular"}
          className={n <= value ? "text-amber-500" : "text-line-strong"}
        />
      ))}
    </span>
  );
}

export default function OrdersPage() {
  return (
    <div className="flex min-h-[100dvh] flex-col">
      <SiteHeader />
      <AuthGate>
        <main className="mx-auto w-full max-w-2xl flex-1 px-4 py-6">
          <Link
            href="/"
            className="mb-4 inline-flex items-center gap-1.5 text-[13.5px] text-ink-muted hover:text-accent"
          >
            <ArrowLeftIcon size={15} />
            Back to DineMate
          </Link>
          <h1 className="mb-4 text-[19px] font-semibold tracking-tight text-ink">
            Your orders
          </h1>
          <OrderList />
        </main>
      </AuthGate>
    </div>
  );
}
