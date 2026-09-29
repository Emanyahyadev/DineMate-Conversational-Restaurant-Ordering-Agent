"use client";

import { MinusIcon, PlusIcon, TrashIcon } from "@phosphor-icons/react/dist/ssr";

import type { Cart } from "@/lib/api";

/**
 * The order, always visible and always server-truth.
 *
 * The cart is never derived from chat text: it is the `cart` SSE snapshot and
 * the response of each mutation. A total the customer cannot see is not
 * informed consent (PRD US-29), which is why the total bar is persistent.
 */
export default function CartPanel({
  cart,
  canPlace,
  busy,
  onSetQuantity,
  onRemove,
  onPlace,
}: {
  cart: Cart | null;
  canPlace: boolean;
  busy: boolean;
  onSetQuantity: (lineId: string, quantity: number) => void;
  onRemove: (lineId: string) => void;
  onPlace: () => void;
}) {
  const lines = cart?.lines ?? [];
  const groups = cart?.restaurants ?? [];

  return (
    // Sizes to its contents rather than stretching: the list caps itself and
    // scrolls, so the summary and the Place order button are always in view.
    <div className="flex max-h-full flex-col">
      <div className="shrink-0 border-b border-line px-4 py-3.5">
        <h2 className="text-[15px] font-semibold tracking-tight text-ink">Your order</h2>
        <p className="text-[13px] text-ink-muted">
          {lines.length === 0
            ? "Nothing yet"
            : `${lines.reduce((n, l) => n + l.quantity, 0)} item${
                lines.reduce((n, l) => n + l.quantity, 0) === 1 ? "" : "s"
              }` +
              (groups.length > 1 ? ` from ${groups.length} kitchens` : "")}
        </p>
      </div>

      <div
        className={`min-h-0 overflow-y-auto px-4 ${
          lines.length === 0 ? "py-2" : "max-h-[30vh] py-3"
        }`}
      >
        {lines.length === 0 ? (
          <p className="pb-2 text-[13px] leading-snug text-ink-muted">
            Nothing yet. Ask DineMate what is good, or tap a dish.
          </p>
        ) : (
          <div className="flex flex-col gap-3">
            {groups.map((group) => (
              <section key={group.restaurant_id}>
                {groups.length > 1 && (
                  <div className="mb-1.5 flex items-baseline justify-between gap-2">
                    <h3 className="text-[12.5px] font-semibold uppercase tracking-wide text-ink-muted">
                      {group.restaurant_name}
                    </h3>
                    <span className="text-[12.5px] tabular-nums text-ink-muted">
                      {group.subtotal_display}
                    </span>
                  </div>
                )}
                <ul className="flex flex-col gap-3">
                  {/* Name gets its own row: sharing one row with the stepper and
                      the line total truncated dish names down to "Margh...". */}
                  {group.lines.map((line) => (
              <li key={line.line_id} className="flex flex-col gap-1">
                <div className="flex items-baseline justify-between gap-2">
                  <p className="min-w-0 flex-1 text-[14px] font-medium text-ink">
                    {line.name}
                  </p>
                  <p className="shrink-0 text-[14px] font-medium tabular-nums text-ink">
                    {line.line_total_display}
                  </p>
                </div>
                {line.options.length > 0 && (
                  <p className="text-[12.5px] text-ink-muted">
                    {line.options.map((o) => o.name).join(", ")}
                  </p>
                )}

                <div className="flex items-center gap-1">
                  <span className="mr-auto text-[13px] text-ink-muted">
                    {line.unit_price_display} each
                  </span>
                  <button
                    type="button"
                    onClick={() => onSetQuantity(line.line_id, line.quantity - 1)}
                    disabled={busy}
                    aria-label={`One fewer ${line.name}`}
                    className="flex size-11 items-center justify-center rounded-full text-ink-soft transition-colors hover:bg-canvas disabled:opacity-40"
                  >
                    <MinusIcon size={14} />
                  </button>
                  <span
                    className="min-w-[1.5rem] text-center text-[14px] font-medium tabular-nums text-ink"
                    aria-label={`Quantity ${line.quantity}`}
                  >
                    {line.quantity}
                  </span>
                  <button
                    type="button"
                    onClick={() => onSetQuantity(line.line_id, line.quantity + 1)}
                    disabled={busy || line.quantity >= 20}
                    aria-label={`One more ${line.name}`}
                    className="flex size-11 items-center justify-center rounded-full text-ink-soft transition-colors hover:bg-canvas disabled:opacity-40"
                  >
                    <PlusIcon size={14} />
                  </button>
                  <button
                    type="button"
                    onClick={() => onRemove(line.line_id)}
                    disabled={busy}
                    aria-label={`Remove ${line.name}`}
                    className="flex size-11 items-center justify-center rounded-full text-ink-soft transition-colors hover:bg-danger-soft hover:text-danger disabled:opacity-40"
                  >
                    <TrashIcon size={14} />
                  </button>
                </div>
              </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
        )}
      </div>

      {lines.length > 0 && cart && (
        <div className="shrink-0 border-t border-line px-4 py-3.5">
          <dl className="mb-3 flex flex-col gap-1 text-[13.5px]">
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

          <button
            type="button"
            onClick={onPlace}
            disabled={!canPlace || busy}
            className="w-full rounded-full bg-accent px-4 py-3 text-[14.5px] font-medium text-white transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-45"
          >
            {busy ? "Placing…" : `Place order — ${cart.total_display}`}
          </button>
          <p className="mt-2 text-center text-[12.5px] leading-snug text-ink-muted">
            {!canPlace
              ? "Review your order with DineMate first, then this unlocks."
              : groups.length > 1
                ? `Placed as ${groups.length} orders, one per kitchen. Pay on collection.`
                : "Pay on collection. You can cancel within 10 minutes."}
          </p>
        </div>
      )}
    </div>
  );
}
