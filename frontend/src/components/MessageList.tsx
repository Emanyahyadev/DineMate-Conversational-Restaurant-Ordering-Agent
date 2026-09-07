"use client";

import BrandMark from "@/components/BrandMark";
import RichText from "@/components/RichText";

export type Message = { role: "user" | "assistant"; content: string };

function AgentMark() {
  return (
    <span className="mt-0.5 block">
      <BrandMark size={28} />
    </span>
  );
}

export function MessageRow({ message }: { message: Message }) {
  const isUser = message.role === "user";

  return (
    <div
      className={`animate-message-in flex gap-2.5 ${
        isUser ? "justify-end" : "justify-start"
      }`}
    >
      {!isUser && <AgentMark />}
      <div
        className={`max-w-[min(34rem,85%)] rounded-2xl px-4 py-2.5 text-[14.5px] leading-relaxed ${
          isUser ? "whitespace-pre-wrap bg-accent text-white" : "bg-canvas text-ink"
        }`}
      >
        {/* Customer text is rendered verbatim; only the agent's replies are
            parsed, and even then into React elements, never raw HTML. */}
        {isUser ? message.content : <RichText text={message.content} />}
      </div>
    </div>
  );
}

export function TypingRow() {
  return (
    <div className="animate-message-in flex gap-2.5">
      <AgentMark />
      <div className="flex items-center gap-1.5 rounded-2xl bg-canvas px-4 py-3.5">
        {[0, 1, 2].map((dot) => (
          <span
            key={dot}
            className="animate-dot size-1.5 rounded-full bg-ink-muted"
            style={{ animationDelay: `${dot * 160}ms` }}
          />
        ))}
        <span className="sr-only">The agent is replying</span>
      </div>
    </div>
  );
}
