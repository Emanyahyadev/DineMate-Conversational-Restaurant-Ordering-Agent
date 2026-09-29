"use client";

import { useEffect, useRef, useState } from "react";

import type { Cart, Checkout } from "@/lib/api";

/**
 * The deliberate order-placement step, and the only place contact details are
 * collected.
 *
 * Placing an order is never inferred: it needs this explicit confirmation, with
 * every line, the server-computed total, and where the food is going all in
 * view. Focus is trapped and restored, and Escape cancels (FRONTEND_SPEC §4, §7).
 */
export default function ConfirmDialog({
  cart,
  savedPhone,
  savedAddress,
  deliveryFeeDisplay,
  busy,
  error,
  onConfirm,
  onCancel,
}: {
  cart: Cart;
  savedPhone: string;
  savedAddress: string;
  deliveryFeeDisplay: string;
  busy: boolean;
  error: string | null;
  onConfirm: (checkout: Checkout) => void;
  onCancel: () => void;
}) {
  const groups = cart.restaurants ?? [];

  const [fulfilment, setFulfilment] = useState<"pickup" | "delivery">("pickup");
  const [phone, setPhone] = useState(savedPhone);
  const [address, setAddress] = useState(savedAddress);
  const [notes, setNotes] = useState("");
  const [touched, setTouched] = useState(false);

  // Details carried over from a previous order are labelled rather than just
  // appearing in the box. A returning customer should be able to see at a
  // glance what we kept and correct it, not wonder where it came from.
  const remembered = { phone: savedPhone, address: savedAddress };
  const phoneIsRemembered = Boolean(savedPhone) && phone === remembered.phone;
  const addressIsRemembered = Boolean(savedAddress) && address === remembered.address;

  const dialogRef = useRef<HTMLFormElement>(null);
  const restoreTo = useRef<HTMLElement | null>(null);

  useEffect(() => {
    restoreTo.current = document.activeElement as HTMLElement | null;
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
        "button:not([disabled]), input:not([disabled]), textarea:not([disabled])",
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

  // The server is still the authority on money; this only renders the delivery
  // line the customer is about to agree to (Rule $5 - the parts come from the
  // server, the arithmetic here never decides anything).
  const feeCents = parseFee(deliveryFeeDisplay);
  const totalCents =
    cart.total_cents + (fulfilment === "delivery" ? feeCents * groups.length : 0);
  const totalDisplay = formatLike(deliveryFeeDisplay, totalCents);

  const phoneOk = phone.trim().length >= 7;
  const addressOk = fulfilment === "pickup" || address.trim().length >= 8;
  const ready = phoneOk && addressOk;

  function submit(event: React.FormEvent) {
    event.preventDefault();
    setTouched(true);
    if (!ready || busy) return;
    onConfirm({
      fulfilment,
      contact_phone: phone.trim(),
      delivery_address: fulfilment === "delivery" ? address.trim() : "",
      notes: notes.trim(),
    });
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center p-0 sm:items-center sm:p-4">
      <button
        type="button"
        aria-label="Cancel"
        onClick={() => !busy && onCancel()}
        className="absolute inset-0 bg-ink/35"
      />
      <form
        ref={dialogRef}
        onSubmit={submit}
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        className="relative flex max-h-[88dvh] w-full max-w-md flex-col overflow-hidden rounded-t-2xl bg-surface shadow-xl sm:rounded-2xl"
      >
        <div className="shrink-0 border-b border-line px-5 py-4">
          <h2 id="confirm-title" className="text-[16px] font-semibold tracking-tight text-ink">
            {groups.length > 1 ? `Place ${groups.length} orders?` : "Place this order?"}
          </h2>
          <p className="mt-0.5 text-[13px] text-ink-muted">
            {groups.length > 1
              ? "One per kitchen, since each cooks separately. Pay on collection."
              : "Pay on collection or on delivery."}
          </p>
        </div>

        {/* Scrolls internally so nothing is clipped on a short screen. */}
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {groups.map((group) => (
            <section key={group.restaurant_id} className="mb-3 last:mb-0">
              {groups.length > 1 && (
                <div className="mb-1.5 flex items-baseline justify-between gap-2 border-b border-line pb-1">
                  <h3 className="text-[13px] font-semibold text-ink">
                    {group.restaurant_name}
                  </h3>
                  <span className="text-[13px] tabular-nums text-ink-muted">
                    {group.subtotal_display}
                  </span>
                </div>
              )}
              <ul className="flex flex-col gap-2">
                {group.lines.map((line) => (
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
            </section>
          ))}

          <fieldset className="mt-4 border-t border-line pt-3">
            <legend className="sr-only">How to get your order</legend>
            <div className="flex gap-2">
              {(["pickup", "delivery"] as const).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => setFulfilment(mode)}
                  aria-pressed={fulfilment === mode}
                  className={`min-h-11 flex-1 rounded-full text-[13.5px] font-medium transition-colors ${
                    fulfilment === mode
                      ? "bg-accent text-white"
                      : "border border-line-strong text-ink-soft hover:bg-canvas"
                  }`}
                >
                  {mode === "pickup" ? "Collect" : "Deliver"}
                </button>
              ))}
            </div>
            {fulfilment === "delivery" && (
              <p className="mt-1.5 text-center text-[12.5px] text-ink-muted">
                {deliveryFeeDisplay} per kitchen, since each sends its own rider.
              </p>
            )}
          </fieldset>

          <div className="mt-3">
            <label htmlFor="co-phone" className="mb-1 flex items-baseline justify-between gap-2 text-[13px] text-ink-soft">
              <span>Phone number</span>
              {phoneIsRemembered && <Remembered />}
            </label>
            <input
              id="co-phone"
              type="tel"
              inputMode="tel"
              autoComplete="tel"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="03xx xxxxxxx"
              aria-invalid={touched && !phoneOk}
              aria-describedby="co-phone-hint"
              className={`w-full rounded-2xl border bg-surface px-3.5 py-3 text-[16px] text-ink outline-none transition-colors focus:border-accent ${
                touched && !phoneOk ? "border-danger" : "border-line-strong"
              }`}
            />
            <p id="co-phone-hint" className="mt-1 text-[12px] text-ink-muted">
              {touched && !phoneOk
                ? "We need a number the kitchen can call."
                : "So the kitchen can reach you about this order."}
            </p>
          </div>

          {fulfilment === "delivery" && (
            <div className="mt-3">
              <label htmlFor="co-address" className="mb-1 flex items-baseline justify-between gap-2 text-[13px] text-ink-soft">
                <span>Delivery address</span>
                {addressIsRemembered && <Remembered />}
              </label>
              <textarea
                id="co-address"
                rows={2}
                autoComplete="street-address"
                value={address}
                onChange={(e) => setAddress(e.target.value)}
                placeholder="House, street, area, city"
                aria-invalid={touched && !addressOk}
                className={`w-full resize-none rounded-2xl border bg-surface px-3.5 py-3 text-[16px] text-ink outline-none transition-colors focus:border-accent ${
                  touched && !addressOk ? "border-danger" : "border-line-strong"
                }`}
              />
              {touched && !addressOk && (
                <p className="mt-1 text-[12px] text-danger">
                  We need somewhere to deliver to.
                </p>
              )}
            </div>
          )}

          <div className="mt-3">
            <label htmlFor="co-notes" className="mb-1 block text-[13px] text-ink-soft">
              Anything else? <span className="text-ink-muted">(optional)</span>
            </label>
            <input
              id="co-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Less spicy, extra raita…"
              className="w-full rounded-2xl border border-line-strong bg-surface px-3.5 py-3 text-[16px] text-ink outline-none focus:border-accent"
            />
          </div>

          <dl className="mt-4 flex flex-col gap-1 border-t border-line pt-3 text-[13.5px]">
            <Row label="Subtotal" value={cart.subtotal_display} />
            <Row label="Tax" value={cart.tax_display} />
            {fulfilment === "delivery" && (
              <Row
                label={`Delivery${groups.length > 1 ? ` × ${groups.length}` : ""}`}
                value={formatLike(deliveryFeeDisplay, feeCents * groups.length)}
              />
            )}
            <div className="flex justify-between pt-1 text-[15px] font-semibold text-ink">
              <dt>Total</dt>
              <dd className="tabular-nums">{totalDisplay}</dd>
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
            type="submit"
            disabled={busy}
            className="flex-1 rounded-full bg-accent px-4 py-3 text-[14.5px] font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-45"
          >
            {busy ? "Placing…" : groups.length > 1 ? "Yes, place them" : "Yes, place it"}
          </button>
        </div>
      </form>
    </div>
  );
}

/** "Rs 150" -> 150. The server sends both forms; only the digits are needed. */
function parseFee(display: string): number {
  const digits = display.replace(/[^0-9]/g, "");
  return digits ? Number(digits) : 0;
}

/** Reuse the server's own currency shape rather than inventing a second one. */
function formatLike(sample: string, minor: number): string {
  const symbol = sample.replace(/[0-9.,\s]/g, "");
  return `${symbol} ${minor.toLocaleString()}`;
}

/** Marks a field we filled in from the customer's last order. */
function Remembered() {
  return (
    <span className="rounded-full bg-accent-soft px-2 py-0.5 text-[11.5px] font-medium text-accent">
      From last time
    </span>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between text-ink-muted">
      <dt>{label}</dt>
      <dd className="tabular-nums">{value}</dd>
    </div>
  );
}
