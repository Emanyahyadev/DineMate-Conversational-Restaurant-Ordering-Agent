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
}: {
  conversations: ConversationSummary[];
  activeId: string | null;
  busy: boolean;
  onNew: () => void;
  onOpen: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  const shown = conversations.filter((c) => !c.empty || c.id === activeId);

  return (
    <div className="flex max-h-full flex-col">
      <div className="shrink-0 border-b border-line px-4 py-3.5">
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

      {shown.length > 0 && (
        <ul className="max-h-[22vh] min-h-0 overflow-y-auto px-2 py-2">
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
