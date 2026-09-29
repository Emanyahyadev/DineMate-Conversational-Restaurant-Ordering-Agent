"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowClockwiseIcon,
  BasketIcon,
  WarningCircleIcon,
  XIcon,
} from "@phosphor-icons/react/dist/ssr";

import CartPanel from "@/components/CartPanel";
import ChatHistory from "@/components/ChatHistory";
import Composer from "@/components/Composer";
import ConfirmDialog from "@/components/ConfirmDialog";
import MenuPanel from "@/components/MenuPanel";
import { MessageRow, TypingRow, type Message } from "@/components/MessageList";
import * as api from "@/lib/api";

const FALLBACK_GREETING =
  "Hi, I am DineMate. I can show you what our restaurants are cooking, take your " +
  "order, or check on one you have already placed. What are you in the mood for?";

const STARTERS = [
  "What's on the menu?",
  "Show me something vegetarian",
  "I would like a chicken biryani",
  "Where is my order?",
];

export default function Chat() {
  const [messages, setMessages] = useState<Message[]>([
    { role: "assistant", content: FALLBACK_GREETING },
  ]);
  const [conversations, setConversations] = useState<api.ConversationSummary[]>([]);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [switching, setSwitching] = useState(false);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const [toolLabel, setToolLabel] = useState<string | null>(null);
  const [failedMessage, setFailedMessage] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);

  const [cart, setCart] = useState<api.Cart | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [contact, setContact] = useState({ phone: "", address: "" });
  const [deliveryFee, setDeliveryFee] = useState("");
  const [cartBusy, setCartBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [confirmError, setConfirmError] = useState<string | null>(null);

  const [menuOpen, setMenuOpen] = useState(false);
  const [cartOpen, setCartOpen] = useState(false);

  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Which thread the customer last asked to see. A result is applied only if
  // it still matches; anything slower and now-stale is dropped.
  //
  // This tracks INTENT rather than a request counter. A shared counter meant a
  // second increment from an unrelated fetch invalidated a perfectly good
  // result, and the conversation silently refused to open.
  const wanted = useRef<string | null>(null);

  const refreshCart = useCallback(async () => {
    try {
      const r = await api.getCart();
      setCart(r.cart);
      setToken(r.confirmation_token);
      setContact(r.contact);
      setDeliveryFee(r.delivery_fee_display);
    } catch {
      /* signed out or offline: leave the panel as it was */
    }
  }, []);

  const refreshConversations = useCallback(async () => {
    try {
      setConversations((await api.listConversations()).items);
    } catch {
      /* history is a convenience; its absence must not block the chat */
    }
  }, []);

  const loadGreeting = useCallback(async (forConversation: string | null = null) => {
    wanted.current = forConversation;
    try {
      const g = await api.getGreeting();
      // Only greet if the customer has not since opened a past thread.
      if (wanted.current === forConversation) {
        setMessages([{ role: "assistant", content: g.greeting }]);
      }
    } catch {
      if (wanted.current === forConversation) {
        setMessages([{ role: "assistant", content: FALLBACK_GREETING }]);
      }
    }
  }, []);

  useEffect(() => {
    // Not a synchronous setState: each of these awaits its request first.
    // The lint rule cannot see through the async boundary.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refreshCart();
    void refreshConversations();
    void loadGreeting();
  }, [refreshCart, refreshConversations, loadGreeting]);

  const startNewChat = useCallback(async () => {
    setSwitching(true);
    try {
      const { id } = await api.newConversation();
      setConversationId(id);
      await loadGreeting(id);
      await refreshConversations();
    } catch (err) {
      console.error("could not start a new chat", err);
    } finally {
      setSwitching(false);
    }
  }, [loadGreeting, refreshConversations]);

  const openConversation = useCallback(async (id: string) => {
    wanted.current = id;
    setSwitching(true);
    try {
      const { messages: history } = await api.getConversation(id);
      if (wanted.current !== id) return; // they moved on
      setConversationId(id);
      setMessages(
        history.length ? history : [{ role: "assistant", content: FALLBACK_GREETING }],
      );
    } catch (err) {
      console.error("could not open that conversation", err);
    } finally {
      setSwitching(false);
    }
  }, []);

  const removeConversation = useCallback(
    async (id: string) => {
      // Gone from the list immediately - a delete that appears to do nothing
      // until a round trip finishes reads as a broken button. If the server
      // refuses, the thread comes back and says why, rather than the failure
      // being swallowed.
      const before = conversations;
      setHistoryError(null);
      setConversations((current) => current.filter((c) => c.id !== id));

      try {
        await api.deleteConversation(id);
      } catch (err) {
        console.error("could not delete that conversation", err);
        setConversations(before);
        setHistoryError("We could not delete that chat. Please try again.");
        return;
      }

      if (id === conversationId) {
        setConversationId(null);
        await loadGreeting(null);
      }
      await refreshConversations();
    },
    [conversations, conversationId, loadGreeting, refreshConversations],
  );

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, pending]);

  useEffect(() => {
    if (!menuOpen && !cartOpen) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setMenuOpen(false);
        setCartOpen(false);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [menuOpen, cartOpen]);

  const send = useCallback(
    async (text: string, { echo = true }: { echo?: boolean } = {}) => {
      if (!text || pending) return;

      if (echo) setMessages((prev) => [...prev, { role: "user", content: text }]);
      setInput("");
      setPending(true);
      setFailedMessage(null);
      setToolLabel(null);

      // The assistant bubble is created once, on `start`, and every token
      // appends to the last message. The previous version flipped a local
      // `started` flag inside the setState updater; React may invoke an updater
      // more than once, which made the flag lie and the reply vanish.
      try {
        await api.streamChat(text, conversationId, (event) => {
          switch (event.type) {
            case "start":
              setConversationId(event.conversation_id);
              setMessages((prev) => [...prev, { role: "assistant", content: "" }]);
              break;
            case "tool":
              setToolLabel(event.phase === "start" ? event.label : null);
              break;
            case "cart":
              // Server truth, mid-turn: the panel never lags the conversation.
              setCart(event.cart);
              break;
            case "token":
              setMessages((prev) => {
                const copy = [...prev];
                const last = copy[copy.length - 1];
                if (!last || last.role !== "assistant") {
                  return [...prev, { role: "assistant", content: event.delta }];
                }
                copy[copy.length - 1] = {
                  role: "assistant",
                  content: last.content + event.delta,
                };
                return copy;
              });
              break;
            case "error":
              setMessages((prev) => {
                const copy = [...prev];
                const last = copy[copy.length - 1];
                // Replace the empty placeholder rather than leaving a blank bubble.
                if (last && last.role === "assistant" && !last.content) copy.pop();
                return [...copy, { role: "assistant", content: event.message }];
              });
              break;
          }
        });
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          if (last && last.role === "assistant" && !last.content.trim()) {
            return [
              ...prev.slice(0, -1),
              {
                role: "assistant",
                content:
                  "Sorry, I did not manage a reply to that. Could you put it another way?",
              },
            ];
          }
          return prev;
        });
      } catch (err) {
        console.error("chat request failed", err);
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          return last && last.role === "assistant" && !last.content
            ? prev.slice(0, -1)
            : prev;
        });
        setFailedMessage(text);
      } finally {
        setPending(false);
        setToolLabel(null);
        textareaRef.current?.focus();
        void refreshCart();
        void refreshConversations();
      }
    },
    [conversationId, pending, refreshCart, refreshConversations],
  );

  const mutateCart = useCallback(async (fn: () => Promise<{ cart: api.Cart }>) => {
    setCartBusy(true);
    try {
      // The mutation answers with the whole cart, and nothing else on this
      // panel changes: the saved contact details and the delivery fee are the
      // same as they were. Re-reading /api/cart afterwards was a second round
      // trip with every stepper button held disabled for its duration, which
      // is what made tapping "+" twice feel broken.
      setCart((await fn()).cart);
      // Any mutation invalidates the outstanding confirmation (US-15).
      setToken(null);
    } catch (err) {
      console.error("cart update failed", err);
      // Whatever the server actually has now, rather than a guess.
      await refreshCart();
    } finally {
      setCartBusy(false);
    }
  }, [refreshCart]);

  const placeOrder = useCallback(async (checkout: api.Checkout) => {
    if (!token) return;
    setCartBusy(true);
    setConfirmError(null);
    try {
      const { orders } = await api.placeOrder(token, checkout);
      setConfirming(false);
      setCartOpen(false);

      // A basket spanning kitchens becomes one order each. Name them all: a
      // customer who sees one id will assume the rest did not go through.
      const lines = orders.map(
        (o) =>
          `- ${o.restaurant_name}: ${o.id}, ${o.total_display}, about ${o.eta_minutes} minutes`,
      );
      const summary =
        orders.length === 1
          ? `All set, your order is ${orders[0].id} from ${orders[0].restaurant_name}, ${orders[0].total_display}. About ${orders[0].eta_minutes} minutes.`
          : [
              `All set. That is ${orders.length} orders, one per kitchen:`,
              ...lines,
            ].join("\n");

      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: `${summary}\n\nYou can cancel any of them within 10 minutes.`,
        },
      ]);
      await refreshCart();
    } catch (err) {
      setConfirmError(
        err instanceof api.ApiError ? err.message : "That did not go through.",
      );
      await refreshCart();
    } finally {
      setCartBusy(false);
    }
  }, [refreshCart, token]);

  function fillComposer(text: string) {
    setInput(text);
    setMenuOpen(false);
    textareaRef.current?.focus();
  }

  const showStarters = messages.length === 1 && !pending && !failedMessage;
  const itemCount = cart?.lines.reduce((n, l) => n + l.quantity, 0) ?? 0;

  const cartPanel = (
    <CartPanel
      cart={cart}
      canPlace={Boolean(token) && itemCount > 0}
      busy={cartBusy}
      onSetQuantity={(id, q) => void mutateCart(() => api.setLineQuantity(id, q))}
      onRemove={(id) => void mutateCart(() => api.setLineQuantity(id, 0))}
      onPlace={() => {
        setConfirmError(null);
        setConfirming(true);
      }}
    />
  );

  return (
    <>
      {/* Three panes on a wide screen: threads, the conversation, then the
          order and the menu. Stacking all four in one 21rem column left the
          menu with about two visible dishes. */}
      <main className="mx-auto flex w-full max-w-[86rem] min-h-0 flex-1 gap-4 px-3 py-4 sm:px-4 lg:gap-5 lg:px-6">
        <aside className="hidden w-[15rem] shrink-0 overflow-hidden rounded-2xl border border-line bg-surface xl:block">
          <ChatHistory
            conversations={conversations}
            activeId={conversationId}
            busy={switching || pending}
            onNew={() => void startNewChat()}
            onOpen={(id) => void openConversation(id)}
            onDelete={(id) => void removeConversation(id)}
            error={historyError}
            fill
          />
        </aside>

        <section className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-2xl border border-line bg-surface">
          <div className="min-h-0 flex-1 overflow-y-auto px-3 py-5 sm:px-5">
            <div
              className="mx-auto flex max-w-2xl flex-col gap-3"
              aria-live="polite"
              aria-atomic="false"
            >
              {messages.map((message, index) => (
                <MessageRow key={index} message={message} />
              ))}

              {showStarters && (
                <div className="animate-message-in mt-1 pl-[38px]">
                  <p className="mb-2 text-[13px] text-ink-muted">
                    Not sure where to start? Pick one.
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {STARTERS.map((starter) => (
                      <button
                        key={starter}
                        type="button"
                        onClick={() => void send(starter)}
                        className="min-h-11 rounded-full border border-line-strong bg-surface px-3.5 py-2 text-[13.5px] text-ink-soft transition-all hover:border-accent hover:bg-accent-soft hover:text-accent active:translate-y-px"
                      >
                        {starter}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {pending && (
                <>
                  <TypingRow />
                  {toolLabel && (
                    <p
                      aria-busy="true"
                      className="animate-message-in pl-[38px] text-[13px] text-ink-muted"
                    >
                      {toolLabel}...
                    </p>
                  )}
                </>
              )}

              {failedMessage && (
                <div
                  role="alert"
                  className="animate-message-in ml-[38px] rounded-2xl bg-danger-soft px-4 py-3.5"
                >
                  <p className="flex items-start gap-2 text-[13.5px] leading-snug text-danger">
                    <WarningCircleIcon size={17} className="mt-px shrink-0" />
                    <span>
                      Your message did not get through. The kitchen system may be busy.
                    </span>
                  </p>
                  <button
                    type="button"
                    onClick={() => void send(failedMessage, { echo: false })}
                    className="mt-3 inline-flex items-center gap-1.5 rounded-full border border-danger/30 px-3.5 py-1.5 text-[13.5px] font-medium text-danger transition-colors hover:bg-danger/10"
                  >
                    <ArrowClockwiseIcon size={15} />
                    Send it again
                  </button>
                </div>
              )}

              <div ref={bottomRef} />
            </div>
          </div>

          <Composer
            value={input}
            onChange={setInput}
            onSubmit={() => void send(input.trim())}
            onOpenMenu={() => setMenuOpen(true)}
            pending={pending}
            textareaRef={textareaRef}
          />
        </section>

        {/* The order sizes to its contents; the menu takes everything left, so
            it shows a usable number of dishes rather than two clipped rows.
            Below xl the threads panel folds in here. */}
        <aside className="hidden w-[21rem] shrink-0 flex-col gap-4 lg:flex lg:gap-5">
          <div className="shrink-0 overflow-hidden rounded-2xl border border-line bg-surface xl:hidden">
            <ChatHistory
              conversations={conversations}
              activeId={conversationId}
              busy={switching || pending}
              onNew={() => void startNewChat()}
              onOpen={(id) => void openConversation(id)}
              onDelete={(id) => void removeConversation(id)}
              error={historyError}
            />
          </div>
          <div className="shrink-0 overflow-hidden rounded-2xl border border-line bg-surface">
            {cartPanel}
          </div>
          <div className="min-h-0 flex-1 overflow-hidden rounded-2xl border border-line bg-surface">
            <MenuPanel onPick={fillComposer} />
          </div>
        </aside>
      </main>

      {/* Persistent total bar: on a phone the amount is never more than a glance
          away, and it is the way into the order (PRD US-29). */}
      {itemCount > 0 && (
        <button
          type="button"
          onClick={() => setCartOpen(true)}
          className="sticky bottom-0 z-30 flex w-full items-center justify-between gap-3 border-t border-line bg-accent px-4 py-3 text-white lg:hidden"
        >
          <span className="flex items-center gap-2 text-[14.5px] font-medium">
            <BasketIcon size={18} weight="fill" />
            {itemCount} item{itemCount === 1 ? "" : "s"}
          </span>
          <span className="text-[15px] font-semibold tabular-nums">
            {cart?.total_display}
          </span>
        </button>
      )}

      {(menuOpen || cartOpen) && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            type="button"
            aria-label="Close"
            onClick={() => {
              setMenuOpen(false);
              setCartOpen(false);
            }}
            className="absolute inset-0 bg-ink/25"
          />
          <div
            role="dialog"
            aria-modal="true"
            aria-label={cartOpen ? "Your order" : "Today's menu"}
            className="absolute inset-y-0 right-0 flex w-[min(21rem,88vw)] flex-col bg-surface shadow-xl"
          >
            <button
              type="button"
              onClick={() => {
                setMenuOpen(false);
                setCartOpen(false);
              }}
              autoFocus
              className="absolute right-3 top-3 z-10 flex size-11 items-center justify-center rounded-full text-ink-soft transition-colors hover:bg-canvas"
            >
              <XIcon size={18} />
              <span className="sr-only">Close</span>
            </button>
            {cartOpen ? (
              <div className="flex min-h-0 flex-col overflow-y-auto">
                <ChatHistory
                  conversations={conversations}
                  activeId={conversationId}
                  busy={switching || pending}
                  onNew={() => {
                    setCartOpen(false);
                    void startNewChat();
                  }}
                  onOpen={(id) => {
                    setCartOpen(false);
                    void openConversation(id);
                  }}
                  onDelete={(id) => void removeConversation(id)}
                  error={historyError}
                />
                <div className="border-t border-line">{cartPanel}</div>
              </div>
            ) : (
              <MenuPanel onPick={fillComposer} />
            )}
          </div>
        </div>
      )}

      {confirming && cart && (
        <ConfirmDialog
          cart={cart}
          savedPhone={contact.phone}
          savedAddress={contact.address}
          deliveryFeeDisplay={deliveryFee}
          busy={cartBusy}
          error={confirmError}
          onConfirm={(checkout) => void placeOrder(checkout)}
          onCancel={() => setConfirming(false)}
        />
      )}
    </>
  );
}
