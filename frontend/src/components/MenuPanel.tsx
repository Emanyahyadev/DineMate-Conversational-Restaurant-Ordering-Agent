"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ArrowClockwiseIcon,
  BowlFoodIcon,
  BreadIcon,
  CakeIcon,
  FireIcon,
  ForkKnifeIcon,
  GrainsSlashIcon,
  LeafIcon,
  MartiniIcon,
  PizzaIcon,
  PlantIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react/dist/ssr";
import type { Icon } from "@phosphor-icons/react";

import { fetchMenu, type MenuItem } from "@/lib/api";

const CATEGORY_ICON: Record<string, Icon> = {
  starters: BreadIcon,
  pizza: PizzaIcon,
  pasta: BowlFoodIcon,
  salad: PlantIcon,
  sides: BreadIcon,
  dessert: CakeIcon,
  drinks: MartiniIcon,
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

type Status = "loading" | "ready" | "error";

function groupByCategory(items: MenuItem[]): [string, MenuItem[]][] {
  const groups = new Map<string, MenuItem[]>();
  for (const item of items) {
    const bucket = groups.get(item.category);
    if (bucket) bucket.push(item);
    else groups.set(item.category, [item]);
  }
  return [...groups.entries()];
}

/** Kitchens in menu order, each with its own dishes. */
function groupByRestaurant(items: MenuItem[]): [string, string, MenuItem[]][] {
  const groups = new Map<string, { name: string; items: MenuItem[] }>();
  for (const item of items) {
    const bucket = groups.get(item.restaurant_id);
    if (bucket) bucket.items.push(item);
    else groups.set(item.restaurant_id, { name: item.restaurant_name, items: [item] });
  }
  return [...groups.entries()].map(([id, g]) => [id, g.name, g.items]);
}

export default function MenuPanel({
  onPick,
}: {
  /** Called with the item name when a customer taps a dish. */
  onPick: (itemName: string) => void;
}) {
  const [items, setItems] = useState<MenuItem[]>([]);
  const [status, setStatus] = useState<Status>("loading");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const data = await fetchMenu();
        if (cancelled) return;
        setItems(data);
        setStatus("ready");
      } catch {
        if (!cancelled) setStatus("error");
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

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* pr-12 keeps the text clear of the close button in the mobile sheet. */}
      <div className="shrink-0 border-b border-line py-4 pl-5 pr-12">
        <h2 className="text-[15px] font-semibold tracking-tight text-ink">
          Restaurants
        </h2>
        <p className="mt-0.5 text-[13px] leading-snug text-ink-muted">
          Tap a dish to add it to your message. One order comes from one kitchen.
        </p>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
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
              className="mt-3 inline-flex items-center gap-1.5 rounded-full border border-danger/30 px-3 py-1.5 text-[13px] font-medium text-danger transition-colors hover:bg-danger/10"
            >
              <ArrowClockwiseIcon size={15} />
              Try again
            </button>
          </div>
        )}

        {status === "ready" && items.length === 0 && (
          <div className="mx-2 mt-6 text-center">
            <ForkKnifeIcon size={26} className="mx-auto text-ink-muted" />
            <p className="mt-2 text-[13px] leading-snug text-ink-soft">
              The kitchen has not published a menu yet. Ask in the chat and we
              will tell you what is on.
            </p>
          </div>
        )}

        {status === "ready" &&
          groupByRestaurant(items).map(([restaurantId, restaurantName, dishes]) => (
            <section key={restaurantId} className="mb-6 last:mb-0">
              <h3 className="sticky top-0 z-10 -mx-3 mb-1 bg-surface px-5 py-2 text-[14px] font-semibold tracking-tight text-ink">
                {restaurantName}
              </h3>

              {groupByCategory(dishes).map(([category, group]) => {
                const CategoryIcon =
                  CATEGORY_ICON[category.toLowerCase()] ?? ForkKnifeIcon;
                return (
              <section key={category} className="mb-4 last:mb-0">
                <h3 className="flex items-center gap-2 px-2 pb-1 pt-2 text-[13px] font-semibold text-ink-soft">
                  <CategoryIcon size={16} className="text-accent" />
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
                          <span className="block truncate text-[14px] font-medium text-ink">
                            {item.name}
                          </span>
                          {item.description && (
                            <span className="mt-0.5 line-clamp-2 block text-[12.5px] leading-snug text-ink-muted">
                              {item.description}
                            </span>
                          )}
                          {item.dietary_tags.length > 0 && (
                            <span className="mt-1.5 flex flex-wrap items-center gap-1.5">
                              {item.dietary_tags.map((tag) => {
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
                        <span className="shrink-0 font-mono text-[13px] tabular-nums text-ink-soft">
                          {item.price_display}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
                );
              })}
            </section>
          ))}
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
                <div className="animate-skeleton h-3.5 flex-1 rounded-full bg-line" />
                <div className="animate-skeleton h-3.5 w-10 rounded-full bg-line" />
              </div>
            ))}
          </div>
        </div>
      ))}
      <span className="sr-only">Loading the menu</span>
    </div>
  );
}
