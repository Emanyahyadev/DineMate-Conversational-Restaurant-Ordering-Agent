"use client";

import { useState, type ReactNode } from "react";
import Image from "next/image";

import { useAuth } from "@/components/AuthProvider";
import { ApiError } from "@/lib/api";

const MIN_PASSWORD = 12;

/**
 * Everything behind DineMate needs an account: memory and order history are
 * per-customer, and a shared browser must never serve one person another's
 * allergy profile (AUTH_SPEC section 1).
 */
export default function AuthGate({ children }: { children: ReactNode }) {
  const { user, loading, signIn, signUp } = useAuth();
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <p className="text-[14px] text-ink-muted">Loading…</p>
      </div>
    );
  }

  if (user) return <>{children}</>;

  const signup = mode === "signup";

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);

    if (signup && password.length < MIN_PASSWORD) {
      setError(`Please use at least ${MIN_PASSWORD} characters.`);
      return;
    }

    setBusy(true);
    try {
      if (signup) await signUp(email.trim(), password, name.trim() || undefined);
      else await signIn(email.trim(), password);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "We could not sign you in just now.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-1 items-center justify-center overflow-y-auto px-4 py-8">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center text-center">
          <Image
            src="/dinemate-logo.png"
            alt="DineMate"
            width={168}
            height={168}
            priority
            className="h-auto w-[168px]"
          />
          <p className="mt-2 text-[14px] text-ink-muted">
            {signup
              ? "Create an account and I will remember how you like to eat."
              : "Welcome back. Sign in to pick up where you left off."}
          </p>
        </div>

        <form
          onSubmit={submit}
          className="flex flex-col gap-3 rounded-2xl border border-line bg-surface p-5"
        >
          {signup && (
            <div>
              <label htmlFor="name" className="mb-1 block text-[13.5px] text-ink-soft">
                Your name <span className="text-ink-muted">(optional)</span>
              </label>
              <input
                id="name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                autoComplete="name"
                className="w-full rounded-2xl border border-line-strong bg-surface px-3.5 py-3 text-[16px] text-ink outline-none transition-colors focus:border-accent"
              />
            </div>
          )}

          <div>
            <label htmlFor="email" className="mb-1 block text-[13.5px] text-ink-soft">
              Email
            </label>
            <input
              id="email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              /* 16px keeps iOS Safari from zooming on focus (PRD US-28). */
              className="w-full rounded-2xl border border-line-strong bg-surface px-3.5 py-3 text-[16px] text-ink outline-none transition-colors focus:border-accent"
            />
          </div>

          <div>
            <label htmlFor="password" className="mb-1 block text-[13.5px] text-ink-soft">
              Password
            </label>
            <input
              id="password"
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={signup ? "new-password" : "current-password"}
              aria-describedby={signup ? "password-hint" : undefined}
              className="w-full rounded-2xl border border-line-strong bg-surface px-3.5 py-3 text-[16px] text-ink outline-none transition-colors focus:border-accent"
            />
            {signup && (
              <p id="password-hint" className="mt-1 text-[12.5px] text-ink-muted">
                At least {MIN_PASSWORD} characters. Length beats punctuation.
              </p>
            )}
          </div>

          {error && (
            <p role="alert" className="rounded-2xl bg-danger-soft px-3.5 py-2.5 text-[13.5px] text-danger">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={busy}
            className="mt-1 rounded-full bg-accent px-4 py-3 text-[14.5px] font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-45"
          >
            {busy ? "One moment…" : signup ? "Create account" : "Sign in"}
          </button>

          <button
            type="button"
            onClick={() => {
              setMode(signup ? "signin" : "signup");
              setError(null);
            }}
            className="text-[13.5px] text-ink-muted underline-offset-2 hover:text-accent hover:underline"
          >
            {signup ? "I already have an account" : "I am new here"}
          </button>
        </form>
      </div>
    </div>
  );
}
