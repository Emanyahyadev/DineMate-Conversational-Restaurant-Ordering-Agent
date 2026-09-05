import Chat from "@/components/Chat";

export default function Home() {
  return (
    <main className="flex flex-1 flex-col min-h-0">
      <header className="border-b border-black/10 px-4 py-4 dark:border-white/10">
        <div className="mx-auto max-w-2xl">
          <h1 className="text-lg font-semibold">Restaurant Ordering Agent</h1>
          <p className="text-sm opacity-60">
            Browse the menu, place an order, or check where your order is.
          </p>
        </div>
      </header>
      <Chat />
    </main>
  );
}
