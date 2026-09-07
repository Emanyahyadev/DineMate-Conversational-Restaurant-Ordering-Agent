"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeftIcon, WarningCircleIcon } from "@phosphor-icons/react/dist/ssr";

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

function OrderList() {
  const [orders, setOrders] = useState<api.Order[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setOrders((await api.listOrders()).items);
      setError(null);
    } catch (err) {
      setError(err instanceof api.ApiError ? err.message : "Could not load your orders.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

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
        const cancellable =
          order.status === "confirmed" &&
          new Date(order.cancellable_until).getTime() > Date.now();

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
          </li>
        );
      })}
    </ul>
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
