"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowClockwiseIcon,
  BowlFoodIcon,
  BreadIcon,
  CakeIcon,
  CoffeeIcon,
  FireIcon,
  ForkKnifeIcon,
  GrainsSlashIcon,
  LeafIcon,
  PlantIcon,
  StarIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react/dist/ssr";
import type { Icon } from "@phosphor-icons/react";

import { fetchMenuBoard, type MenuBoard, type MenuItem, type Restaurant } from "@/lib/api";

const CATEGORY_ICON: Record<string, Icon> = {
  starters: ForkKnifeIcon,
  bbq: FireIcon,
  "karahi & curries": BowlFoodIcon,
  "biryani & rice": BowlFoodIcon,
  breads: BreadIcon,
  sides: PlantIcon,
  desserts: CakeIcon,
  drinks: CoffeeIcon,
};

const TAG_ICON: Record<string, Icon> = {
  vegetarian: LeafIcon,
  vegan: PlantIcon,
  gluten_free: GrainsSlashIcon,
  spicy: FireIcon,
};

const TAG_LABEL: Record<string, string> = {
  vegetarian: "Vegetarian",
  vegan: "Vegan",
  gluten_free: "Gluten free",
  halal: "Halal",
  spicy: "Spicy",
};

// Halal is true of every dish here, so showing it on all 42 is noise.
const HIDDEN_TAGS = new Set(["halal"]);

type Status = "loading" | "ready" | "error";

/**
 * The last board, kept for the life of the page.
 *
 * On a phone the menu is a drawer that opens and closes all evening, and this
 * component unmounts every time it closes. Without this, each open refetched
 * the whole menu and showed a skeleton for the length of a round trip; with it,
 * every open after the first is instant and the refresh happens behind it.
 */
let cached: MenuBoard | null = null;

function groupByCategory(items: MenuItem[]): [string, MenuItem[]][] {
  const groups = new Map<string, MenuItem[]>();
  for (const item of items) {
    const bucket = groups.get(item.category);
    if (bucket) bucket.push(item);
    else groups.set(item.category, [item]);
  }
  return [...groups.entries()];
}

export default function MenuPanel({
  onPick,
}: {
  /** Called with the dish name when a customer taps it. */
  onPick: (itemName: string) => void;
}) {
  const [items, setItems] = useState<MenuItem[]>(cached?.items ?? []);
  const [restaurants, setRestaurants] = useState<Restaurant[]>(cached?.restaurants ?? []);
  const [active, setActive] = useState<string | null>(cached?.restaurants[0]?.id ?? null);
  const [status, setStatus] = useState<Status>(cached ? "ready" : "loading");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const board = await fetchMenuBoard();
        if (cancelled) return;
        cached = board;
        setItems(board.items);
        setRestaurants(board.restaurants);
        setActive((current) => current ?? board.restaurants[0]?.id ?? null);
        setStatus("ready");
      } catch {
        // A failed refresh behind an already-shown menu is not worth wiping
        // the menu for; only a cold open has nothing to fall back on.
        if (!cancelled && !cached) setStatus("error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const retry = useCallback(() => {
    setStatus("loading");
    setAttempt((n) => n + 1);
  }, []);

  // One kitchen at a time. Five menus stacked in a narrow column meant endless
  // scrolling and no sense of where you were.
  const shown = useMemo(
    () => (active ? items.filter((i) => i.restaurant_id === active) : items),
    [items, active],
  );
  const current = restaurants.find((r) => r.id === active);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 border-b border-line py-3.5 pl-4 pr-12">
        <h2 className="text-[15px] font-semibold tracking-tight text-ink">
          Today&rsquo;s menu
        </h2>
        <p className="mt-0.5 text-[13px] leading-snug text-ink-muted">
          Tap a dish to add it to your message.
        </p>
      </div>

      {status === "ready" && restaurants.length > 0 && (
        <div className="shrink-0 border-b border-line px-2 py-2">
          <div className="flex gap-1.5 overflow-x-auto pb-0.5">
            {restaurants.map((r) => (
              <button
                key={r.id}
                type="button"
                onClick={() => setActive(r.id)}
                aria-pressed={r.id === active}
                className={`shrink-0 rounded-full px-3 py-1.5 text-[12.5px] font-medium transition-colors ${
                  r.id === active
                    ? "bg-accent text-white"
                    : "bg-canvas text-ink-soft hover:text-accent"
                }`}
              >
                {r.name}
              </button>
            ))}
          </div>
          {current && (
            <p className="mt-1.5 flex flex-wrap items-center gap-x-1.5 px-1 text-[12px] leading-snug text-ink-muted">
              <span>
                {current.cuisine} &middot; {current.item_count} dishes
              </span>
              {/* Only shown once somebody has actually rated a completed order
                  here. An unrated kitchen is unknown, not bad, so it says
                  nothing rather than showing a zero. */}
              {current.rating?.average != null && (
                <>
                  <span aria-hidden>&middot;</span>
                  <span className="inline-flex items-center gap-1 text-ink-soft">
                    <StarIcon size={11} weight="fill" className="text-amber-500" />
                    <span className="tabular-nums font-medium">
                      {current.rating.average.toFixed(1)}
                    </span>
                    <span>({current.rating.count})</span>
                  </span>
                </>
              )}
            </p>
          )}
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2">
        {status === "loading" && <MenuSkeleton />}

        {status === "error" && (
          <div className="mx-2 mt-2 rounded-2xl bg-danger-soft px-4 py-4">
            <p className="flex items-start gap-2 text-[13px] leading-snug text-danger">
              <WarningCircleIcon size={17} className="mt-px shrink-0" />
              <span>We could not load the menu just now.</span>
            </p>
            <button
              type="button"
              onClick={retry}
              className="mt-3 inline-flex min-h-11 items-center gap-1.5 rounded-full border border-danger/30 px-3.5 text-[13px] font-medium text-danger transition-colors hover:bg-danger/10"
            >
              <ArrowClockwiseIcon size={15} />
              Try again
            </button>
          </div>
        )}

        {status === "ready" && shown.length === 0 && (
          <div className="mx-2 mt-6 text-center">
            <ForkKnifeIcon size={26} className="mx-auto text-ink-muted" />
            <p className="mt-2 text-[13px] leading-snug text-ink-soft">
              Nothing on this menu yet. Ask in the chat and we will tell you what is on.
            </p>
          </div>
        )}

        {status === "ready" &&
          groupByCategory(shown).map(([category, group]) => {
            const CategoryIcon =
              CATEGORY_ICON[category.toLowerCase()] ?? ForkKnifeIcon;
            return (
              <section key={category} className="mb-3 last:mb-0">
                {/* Sticky, so you always know which course you are looking at. */}
                <h3 className="sticky top-0 z-10 -mx-3 flex items-center gap-2 bg-surface px-5 py-1.5 text-[12.5px] font-semibold uppercase tracking-wide text-ink-muted">
                  <CategoryIcon size={15} className="text-accent" />
                  {category}
                </h3>
                <ul>
                  {group.map((item) => (
                    <li key={item.id}>
                      <button
                        type="button"
                        onClick={() => onPick(item.name)}
                        className="flex w-full items-start gap-3 rounded-2xl px-2 py-2.5 text-left transition-colors hover:bg-accent-soft active:scale-[0.99]"
                      >
                        <span className="min-w-0 flex-1">
                          <span className="block text-[14px] font-medium text-ink">
                            {item.name}
                          </span>
                          {item.description && (
                            <span className="mt-0.5 line-clamp-2 block text-[12.5px] leading-snug text-ink-muted">
                              {item.description}
                            </span>
                          )}
                          {item.dietary_tags.some((t) => !HIDDEN_TAGS.has(t)) && (
                            <span className="mt-1.5 flex flex-wrap items-center gap-1.5">
                              {item.dietary_tags
                                .filter((t) => !HIDDEN_TAGS.has(t))
                                .map((tag) => {
                                  const TagIcon = TAG_ICON[tag];
                                  return (
                                    <span
                                      key={tag}
                                      className="inline-flex items-center gap-1 rounded-full bg-canvas px-2 py-0.5 text-[11.5px] text-ink-soft"
                                    >
                                      {TagIcon && <TagIcon size={12} />}
                                      {TAG_LABEL[tag] ?? tag.replace(/_/g, " ")}
                                    </span>
                                  );
                                })}
                            </span>
                          )}
                        </span>
                        <span className="shrink-0 whitespace-nowrap text-[13px] font-medium tabular-nums text-ink-soft">
                          {item.price_display}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            );
          })}
      </div>
    </div>
  );
}

function MenuSkeleton() {
  return (
    <div className="space-y-5 px-2 py-2" aria-hidden>
      {[0, 1, 2].map((group) => (
        <div key={group}>
          <div className="animate-skeleton h-3.5 w-24 rounded-full bg-line" />
          <div className="mt-3 space-y-3">
            {[0, 1].map((row) => (
              <div key={row} className="flex items-center gap-3">
                <div className="flex-1 space-y-1.5">
                  <div className="animate-skeleton h-3.5 w-2/3 rounded-full bg-line" />
                  <div className="animate-skeleton h-3 w-full rounded-full bg-line" />
                </div>
                <div className="animate-skeleton h-3.5 w-12 rounded-full bg-line" />
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
