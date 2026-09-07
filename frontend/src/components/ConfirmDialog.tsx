"use client";

import { useEffect, useRef } from "react";

import type { Cart } from "@/lib/api";

/**
 * The deliberate order-placement step.
 *
 * Placing an order is never inferred: it needs this explicit confirmation, with
 * every line and the server-computed total in view. Focus is trapped and
 * restored, and Escape cancels (FRONTEND_SPEC section 4 and 7).
 */
export default function ConfirmDialog({
  cart,
  busy,
  error,
  onConfirm,
  onCancel,
}: {
  cart: Cart;
  busy: boolean;
  error: string | null;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const restoreTo = useRef<HTMLElement | null>(null);

  useEffect(() => {
    restoreTo.current = document.activeElement as HTMLElement | null;
    confirmRef.current?.focus();
    return () => restoreTo.current?.focus?.();
  }, []);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !busy) {
        onCancel();
        return;
      }
      if (event.key !== "Tab") return;

      const focusable = dialogRef.current?.querySelectorAll<HTMLElement>(
        "button:not([disabled])",
      );
      if (!focusable?.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [busy, onCancel]);

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center p-0 sm:items-center sm:p-4">
      <button
        type="button"
        aria-label="Cancel"
        onClick={() => !busy && onCancel()}
        className="absolute inset-0 bg-ink/35"
      />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        className="relative flex max-h-[85dvh] w-full max-w-md flex-col overflow-hidden rounded-t-2xl bg-surface shadow-xl sm:rounded-2xl"
      >
        <div className="shrink-0 border-b border-line px-5 py-4">
          <h2 id="confirm-title" className="text-[16px] font-semibold tracking-tight text-ink">
            Place this order?
          </h2>
          <p className="mt-0.5 text-[13px] text-ink-muted">
            Pay on collection. Cancellable for 10 minutes.
          </p>
        </div>

        {/* Scrolls internally so nothing is ever clipped on a short screen. */}
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          <ul className="flex flex-col gap-2.5">
            {cart.lines.map((line) => (
              <li key={line.line_id} className="flex items-baseline justify-between gap-3">
                <span className="text-[14px] text-ink">
                  <span className="font-medium tabular-nums">{line.quantity}×</span>{" "}
                  {line.name}
                </span>
                <span className="shrink-0 text-[14px] tabular-nums text-ink-soft">
                  {line.line_total_display}
                </span>
              </li>
            ))}
          </ul>

          <dl className="mt-4 flex flex-col gap-1 border-t border-line pt-3 text-[13.5px]">
            <div className="flex justify-between text-ink-muted">
              <dt>Subtotal</dt>
              <dd className="tabular-nums">{cart.subtotal_display}</dd>
            </div>
            <div className="flex justify-between text-ink-muted">
              <dt>Tax</dt>
              <dd className="tabular-nums">{cart.tax_display}</dd>
            </div>
            <div className="flex justify-between pt-1 text-[15px] font-semibold text-ink">
              <dt>Total</dt>
              <dd className="tabular-nums">{cart.total_display}</dd>
            </div>
          </dl>

          {error && (
            <p role="alert" className="mt-3 rounded-2xl bg-danger-soft px-3.5 py-2.5 text-[13.5px] text-danger">
              {error}
            </p>
          )}
        </div>

        <div className="flex shrink-0 gap-2 border-t border-line px-5 py-3.5">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="flex-1 rounded-full border border-line-strong px-4 py-3 text-[14.5px] font-medium text-ink-soft transition-colors hover:bg-canvas disabled:opacity-45"
          >
            Not yet
          </button>
          <button
            ref={confirmRef}
            type="button"
            onClick={onConfirm}
            disabled={busy}
            className="flex-1 rounded-full bg-accent px-4 py-3 text-[14.5px] font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-45"
          >
            {busy ? "Placing…" : "Yes, place it"}
          </button>
        </div>
      </div>
    </div>
  );
}
