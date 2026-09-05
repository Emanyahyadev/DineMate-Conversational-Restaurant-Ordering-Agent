"use client";

import { useEffect, useRef, useState } from "react";
import { sendMessage } from "@/lib/api";

type Message = { role: "user" | "assistant"; content: string };

const GREETING: Message = {
  role: "assistant",
  content:
    "Hi! I can walk you through the menu, take your order, or check on an order you already placed. What are you in the mood for?",
};

function useUserId() {
  const [userId, setUserId] = useState("guest");
  useEffect(() => {
    let stored = localStorage.getItem("user_id");
    if (!stored) {
      stored = `user-${crypto.randomUUID().slice(0, 8)}`;
      localStorage.setItem("user_id", stored);
    }
    setUserId(stored);
  }, []);
  return userId;
}

export default function Chat() {
  const [messages, setMessages] = useState<Message[]>([GREETING]);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const userId = useUserId();
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, pending]);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const text = input.trim();
    if (!text || pending) return;

    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setInput("");
    setPending(true);
    setError(null);

    try {
      const data = await sendMessage(text, userId, conversationId);
      setConversationId(data.conversation_id);
      setMessages((prev) => [...prev, { role: "assistant", content: data.reply }]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div className="flex-1 overflow-y-auto px-4 py-6">
        <div className="mx-auto flex max-w-2xl flex-col gap-4">
          {messages.map((message, index) => (
            <div
              key={index}
              className={message.role === "user" ? "flex justify-end" : "flex justify-start"}
            >
              <div
                className={`max-w-[80%] whitespace-pre-wrap rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                  message.role === "user"
                    ? "bg-amber-600 text-white"
                    : "bg-black/5 dark:bg-white/10"
                }`}
              >
                {message.content}
              </div>
            </div>
          ))}

          {pending && (
            <div className="flex justify-start">
              <div className="rounded-2xl bg-black/5 px-4 py-3 text-sm opacity-70 dark:bg-white/10">
                Thinking…
              </div>
            </div>
          )}

          {error && (
            <p className="rounded-lg bg-red-500/10 px-4 py-3 text-sm text-red-600 dark:text-red-400">
              {error}
            </p>
          )}

          <div ref={bottomRef} />
        </div>
      </div>

      <form
        onSubmit={handleSubmit}
        className="border-t border-black/10 px-4 py-4 dark:border-white/10"
      >
        <div className="mx-auto flex max-w-2xl gap-2">
          <input
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="Ask about the menu, or start an order…"
            className="flex-1 rounded-full border border-black/15 bg-transparent px-4 py-3 text-sm outline-none focus:border-amber-600 dark:border-white/20"
          />
          <button
            type="submit"
            disabled={pending || !input.trim()}
            className="rounded-full bg-amber-600 px-5 py-3 text-sm font-medium text-white disabled:opacity-40"
          >
            Send
          </button>
        </div>
      </form>
    </div>
  );
}
