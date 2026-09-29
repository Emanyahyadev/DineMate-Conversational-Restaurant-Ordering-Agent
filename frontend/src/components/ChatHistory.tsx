"use client";

import { ChatCircleIcon, PlusIcon, TrashIcon } from "@phosphor-icons/react/dist/ssr";

import type { ConversationSummary } from "@/lib/api";

/**
 * Past threads, and the way to start a new one.
 *
 * Starting a new conversation clears the transcript, never the memory: what
 * DineMate knows about you lives on your profile, not in a thread
 * (DOMAIN_MODEL Rule V4).
 */
export default function ChatHistory({
  conversations,
  activeId,
  busy,
  onNew,
  onOpen,
  onDelete,
  error = null,
  fill = false,
}: {
  conversations: ConversationSummary[];
  activeId: string | null;
  busy: boolean;
  onNew: () => void;
  onOpen: (id: string) => void;
  onDelete: (id: string) => void;
  /** Shown when a delete failed, so a refused action is never silent. */
  error?: string | null;
  /** Fill the height of its own column, instead of capping at a few rows. */
  fill?: boolean;
}) {
  // No filtering here: the server already omits threads with nothing in them,
  // so `limit` counts real conversations. Filtering client-side meant blank
  // threads used up the page and pushed real history out of the list.
  const shown = conversations;

  return (
    <div className={`flex flex-col ${fill ? "h-full" : "max-h-full"}`}>
      <div className="shrink-0 border-b border-line px-3 py-3">
        <button
          type="button"
          onClick={onNew}
          disabled={busy}
          className="flex min-h-11 w-full items-center justify-center gap-2 rounded-full bg-accent px-4 text-[14px] font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-45"
        >
          <PlusIcon size={16} weight="bold" />
          New chat
        </button>
      </div>

      {error && (
        <p role="alert" className="shrink-0 px-3 py-2 text-[12.5px] text-danger">
          {error}
        </p>
      )}

      {shown.length > 0 && (
        <ul
          className={`min-h-0 overflow-y-auto px-2 py-2 ${
            fill ? "flex-1" : "max-h-[22vh]"
          }`}
        >
          {shown.map((c) => (
            <li key={c.id} className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => onOpen(c.id)}
                className={`flex min-w-0 flex-1 items-center gap-2 rounded-2xl px-2.5 py-2 text-left text-[13.5px] transition-colors ${
                  c.id === activeId
                    ? "bg-accent-soft text-accent"
                    : "text-ink-soft hover:bg-canvas"
                }`}
              >
                <ChatCircleIcon size={15} className="shrink-0" />
                <span className="truncate">{c.title}</span>
              </button>
              <button
                type="button"
                onClick={() => onDelete(c.id)}
                aria-label={`Delete conversation: ${c.title}`}
                className="flex size-11 shrink-0 items-center justify-center rounded-full text-ink-muted transition-colors hover:bg-danger-soft hover:text-danger"
              >
                <TrashIcon size={14} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
