"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeftIcon, TrashIcon } from "@phosphor-icons/react/dist/ssr";

import AuthGate from "@/components/AuthGate";
import SiteHeader from "@/components/SiteHeader";
import { useAuth } from "@/components/AuthProvider";
import * as api from "@/lib/api";

/**
 * What DineMate remembers, and the button that makes it forget.
 *
 * Every stored memory is visible and deletable by its owner (PRD US-24). An
 * allergy is flagged because removing one changes what the agent will offer.
 */
function Memories() {
  const [prefs, setPrefs] = useState<api.Memory[]>([]);
  const [facts, setFacts] = useState<api.Memory[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const r = await api.getMemories();
      setPrefs(r.preferences);
      setFacts(r.facts);
    } catch {
      /* memory is degradable: an empty list is the honest fallback */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Not a synchronous setState: each of these awaits its request first.
    // The lint rule cannot see through the async boundary.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  async function forget(id: string) {
    await api.forgetMemory(id).catch(() => undefined);
    await load();
  }

  const all = [...facts, ...prefs];

  if (loading) {
    return <div className="h-24 animate-pulse rounded-2xl border border-line bg-surface" />;
  }

  return (
    <section className="rounded-2xl border border-line bg-surface p-5">
      <h2 className="text-[15px] font-semibold tracking-tight text-ink">
        What DineMate remembers
      </h2>
      <p className="mt-0.5 text-[13px] text-ink-muted">
        Used to make better suggestions. Delete anything you would rather it forgot.
      </p>

      {all.length === 0 ? (
        <p className="mt-4 text-[13.5px] text-ink-muted">
          Nothing yet. Mention a preference or an allergy in the chat and it will show up here.
        </p>
      ) : (
        <ul className="mt-4 flex flex-col gap-2">
          {all.map((memory) => (
            <li
              key={memory.id}
              className="flex items-center gap-2 rounded-2xl bg-canvas px-3.5 py-2.5"
            >
              <span className="min-w-0 flex-1 text-[13.5px] text-ink">
                {memory.text}
                {memory.kind === "allergy" && (
                  <span className="ml-2 rounded-full bg-danger-soft px-2 py-0.5 text-[11.5px] font-medium text-danger">
                    allergy
                  </span>
                )}
              </span>
              <button
                type="button"
                onClick={() => void forget(memory.id)}
                aria-label={`Forget: ${memory.text}`}
                className="flex size-11 shrink-0 items-center justify-center rounded-full text-ink-muted transition-colors hover:bg-danger-soft hover:text-danger"
              >
                <TrashIcon size={15} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Account() {
  const { user, signOut } = useAuth();
  const [stats, setStats] = useState<{ orders_placed: number } | null>(null);

  useEffect(() => {
    api
      .getProfile()
      .then((r) => setStats(r.stats))
      .catch(() => undefined);
  }, []);

  return (
    <section className="rounded-2xl border border-line bg-surface p-5">
      <h2 className="text-[15px] font-semibold tracking-tight text-ink">Account</h2>
      <dl className="mt-3 flex flex-col gap-2 text-[13.5px]">
        <div className="flex justify-between gap-3">
          <dt className="text-ink-muted">Email</dt>
          <dd className="truncate text-ink">{user?.email}</dd>
        </div>
        {user?.display_name && (
          <div className="flex justify-between gap-3">
            <dt className="text-ink-muted">Name</dt>
            <dd className="text-ink">{user.display_name}</dd>
          </div>
        )}
        <div className="flex justify-between gap-3">
          <dt className="text-ink-muted">Orders placed</dt>
          <dd className="tabular-nums text-ink">{stats?.orders_placed ?? "—"}</dd>
        </div>
      </dl>

      <button
        type="button"
        onClick={() => void signOut()}
        className="mt-4 w-full rounded-full border border-line-strong px-4 py-3 text-[14px] font-medium text-ink-soft transition-colors hover:bg-canvas"
      >
        Sign out
      </button>
    </section>
  );
}

export default function ProfilePage() {
  return (
    <div className="flex min-h-[100dvh] flex-col">
      <SiteHeader />
      <AuthGate>
        <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-4 px-4 py-6">
          <Link
            href="/"
            className="inline-flex items-center gap-1.5 text-[13.5px] text-ink-muted hover:text-accent"
          >
            <ArrowLeftIcon size={15} />
            Back to DineMate
          </Link>
          <h1 className="text-[19px] font-semibold tracking-tight text-ink">Your profile</h1>
          <Account />
          <Memories />
        </main>
      </AuthGate>
    </div>
  );
}
