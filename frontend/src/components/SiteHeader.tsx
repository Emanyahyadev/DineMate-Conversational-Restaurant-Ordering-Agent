"use client";

import Link from "next/link";
import { ClockCounterClockwiseIcon, UserIcon } from "@phosphor-icons/react/dist/ssr";

import BrandMark from "@/components/BrandMark";
import { useAuth } from "@/components/AuthProvider";

export default function SiteHeader() {
  const { user, signOut } = useAuth();

  return (
    <header className="shrink-0 border-b border-line bg-surface">
      <div className="mx-auto flex h-[68px] max-w-6xl items-center gap-2.5 px-4 lg:px-6">
        <Link href="/" className="flex min-w-0 items-center gap-2.5">
          <BrandMark size={40} priority />
          <div className="min-w-0">
            <p className="truncate text-[15px] font-semibold leading-tight tracking-tight text-ink">
              DineMate
            </p>
            <p className="truncate text-[13px] leading-tight text-ink-muted">
              Your AI restaurant assistant
            </p>
          </div>
        </Link>

        {user && (
          <nav className="ml-auto flex items-center gap-1">
            <Link
              href="/orders"
              className="flex size-11 items-center justify-center rounded-full text-ink-soft transition-colors hover:bg-canvas hover:text-accent"
              aria-label="Your orders"
            >
              <ClockCounterClockwiseIcon size={19} />
            </Link>
            <Link
              href="/profile"
              className="flex size-11 items-center justify-center rounded-full text-ink-soft transition-colors hover:bg-canvas hover:text-accent"
              aria-label="Your profile"
            >
              <UserIcon size={19} />
            </Link>
            <button
              type="button"
              onClick={() => void signOut()}
              className="ml-1 hidden min-h-11 rounded-full border border-line-strong px-3.5 text-[13.5px] text-ink-soft transition-colors hover:bg-canvas sm:block"
            >
              Sign out
            </button>
          </nav>
        )}
      </div>
    </header>
  );
}
