"use client";

import { useEffect, type RefObject } from "react";
import {
  ListBulletsIcon,
  PaperPlaneTiltIcon,
} from "@phosphor-icons/react/dist/ssr";

const MAX_HEIGHT = 132;

export default function Composer({
  value,
  onChange,
  onSubmit,
  onOpenMenu,
  pending,
  textareaRef,
}: {
  value: string;
  onChange: (next: string) => void;
  onSubmit: () => void;
  onOpenMenu: () => void;
  pending: boolean;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
}) {
  // Grow the box with the message instead of scrolling a one-line field.
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`;
  }, [value, textareaRef]);

  const canSend = value.trim().length > 0 && !pending;

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
      className="shrink-0 border-t border-line bg-surface px-3 py-3 sm:px-4"
    >
      <div className="flex items-end gap-2">
        <div className="flex min-w-0 flex-1 items-end rounded-2xl border border-line-strong bg-surface transition-colors focus-within:border-accent">
          <label htmlFor="composer" className="sr-only">
            Message the restaurant
          </label>
          <textarea
            id="composer"
            ref={textareaRef}
            rows={1}
            value={value}
            disabled={pending}
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                if (canSend) onSubmit();
              }
            }}
            placeholder="Type your question or your order"
            className="max-h-[132px] w-full resize-none bg-transparent px-4 py-3 text-[14.5px] leading-relaxed text-ink outline-none placeholder:text-ink-muted disabled:opacity-60"
          />
        </div>

        <button
          type="submit"
          disabled={!canSend}
          className="flex h-11 shrink-0 items-center gap-1.5 rounded-full bg-accent px-4 text-[14px] font-medium text-white transition-all hover:bg-accent-hover active:translate-y-px disabled:cursor-not-allowed disabled:bg-line-strong disabled:text-ink-soft"
        >
          <PaperPlaneTiltIcon size={17} />
          Send
        </button>
      </div>

      <div className="mt-2 flex items-center justify-between gap-3 px-1">
        <button
          type="button"
          onClick={onOpenMenu}
          className="inline-flex items-center gap-1.5 rounded-full border border-line-strong px-3 py-1.5 text-[13px] font-medium text-ink-soft transition-colors hover:bg-canvas lg:hidden"
        >
          <ListBulletsIcon size={16} />
          Browse the menu
        </button>
        <p className="hidden text-[12px] text-ink-muted sm:block">
          Press Enter to send. Shift and Enter starts a new line.
        </p>
      </div>
    </form>
  );
}
