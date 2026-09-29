"use client";

import { useEffect, useRef, useState } from "react";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { EyeIcon, EyeSlashIcon } from "@phosphor-icons/react/dist/ssr";

import { useAuth } from "@/components/AuthProvider";
import { ApiError, type User } from "@/lib/api";

/**
 * The one way into DineMate, for both kinds of account.
 *
 * There used to be two sign-in screens: a centred card for customers on `/`,
 * and a two-panel screen for restaurants on `/kitchen`. Same product, two front
 * doors, and no way to reach one from the other. This is that second layout -
 * the brand holding one half, the work happening in the other - with the two
 * audiences as a choice inside it.
 *
 * The tabs only decide what the form offers. WHERE somebody lands is decided by
 * the role on the account the server returns, never by what they picked here:
 * a customer who taps "Restaurant" gets the customer app, not an empty portal.
 */

const MIN_PASSWORD = 12;

type Audience = "customer" | "restaurant";

export default function AuthPanel({
  initialAudience = "customer",
}: {
  initialAudience?: Audience;
}) {
  const router = useRouter();
  const { signIn, signUp } = useAuth();

  const [audience, setAudience] = useState<Audience>(initialAudience);
  const [signup, setSignup] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [reveal, setReveal] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const emailRef = useRef<HTMLInputElement>(null);

  // Both destinations are warmed while somebody is still typing, so the hop
  // after a successful sign-in is a render rather than a page load.
  useEffect(() => {
    router.prefetch("/");
    router.prefetch("/kitchen");
  }, [router]);

  function pick(next: Audience) {
    if (next === audience) return;
    setAudience(next);
    // A restaurant account is created by DineMate, never self-served.
    if (next === "restaurant") setSignup(false);
    setError(null);
    emailRef.current?.focus();
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    setError(null);

    if (signup && password.length < MIN_PASSWORD) {
      setError(`Please use at least ${MIN_PASSWORD} characters.`);
      return;
    }

    setBusy(true);
    try {
      const user: User = signup
        ? await signUp(email.trim(), password, name.trim() || undefined)
        : await signIn(email.trim(), password);
      // The account decides where you land, not the tab.
      router.replace(user.role === "staff" ? "/kitchen" : "/");
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : signup
            ? "We could not create that account just now."
            : "We could not sign you in just now.",
      );
      setBusy(false);
    }
    // Deliberately still busy on success: the route change is the next frame,
    // and re-enabling the button first invites a second submit.
  }

  const restaurant = audience === "restaurant";

  return (
    <div className="grid min-h-full flex-1 bg-dash-bg lg:grid-cols-2">
      <div className="flex items-center justify-center border-b border-dash-line bg-dash-raised px-6 py-12 lg:border-b-0 lg:border-r lg:py-0">
        <Image
          src="/dinemate-logo.png"
          alt="DineMate"
          width={480}
          height={480}
          priority
          className="h-auto w-[170px] select-none sm:w-[240px] lg:w-[330px]"
        />
      </div>

      <div className="flex items-center justify-center overflow-y-auto px-6 py-12 lg:py-0">
        <div className="w-full max-w-[360px]">
          {/* The two doors, side by side and equal. Neither is a link buried
              under the form: whichever you need is one tap from here. */}
          <div
            role="tablist"
            aria-label="Sign in as"
            className="flex gap-1 rounded-xl bg-dash-raised p-1"
          >
            {(["customer", "restaurant"] as const).map((option) => {
              const on = audience === option;
              return (
                <button
                  key={option}
                  type="button"
                  role="tab"
                  aria-selected={on}
                  onClick={() => pick(option)}
                  className={`min-h-11 flex-1 rounded-lg px-3 text-[13.5px] font-medium transition-colors ${
                    on
                      ? "bg-dash-surface text-dash-ink shadow-sm"
                      : "text-dash-muted hover:text-dash-soft"
                  }`}
                >
                  {option === "customer" ? "As a customer" : "As a restaurant"}
                </button>
              );
            })}
          </div>

          <h1 className="mt-8 text-[26px] font-semibold leading-tight tracking-tight text-dash-ink">
            {signup ? "Create your account" : "Welcome back"}
          </h1>
          <p className="mt-2 text-[14.5px] leading-relaxed text-dash-muted">
            {restaurant
              ? "Sign in to your restaurant dashboard."
              : signup
                ? "Create an account and I will remember how you like to eat."
                : "Sign in to pick up where you left off."}
          </p>

          <form onSubmit={submit} className="mt-8">
            {signup && (
              <>
                <label
                  htmlFor="a-name"
                  className="mb-1.5 block text-[13px] font-medium text-dash-soft"
                >
                  Your name <span className="font-normal text-dash-muted">(optional)</span>
                </label>
                <input
                  id="a-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  autoComplete="name"
                  className="dash-field mb-4 w-full rounded-lg border border-dash-line-strong bg-dash-surface px-3.5 py-2.5 text-[16px] text-dash-ink outline-none transition-colors focus:border-dash-accent"
                />
              </>
            )}

            <label
              htmlFor="a-email"
              className="mb-1.5 block text-[13px] font-medium text-dash-soft"
            >
              Email
            </label>
            <input
              id="a-email"
              ref={emailRef}
              type="email"
              required
              autoFocus
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              aria-invalid={Boolean(error)}
              /* 16px keeps iOS Safari from zooming on focus (PRD US-28). */
              className="dash-field mb-4 w-full rounded-lg border border-dash-line-strong bg-dash-surface px-3.5 py-2.5 text-[16px] text-dash-ink outline-none transition-colors focus:border-dash-accent"
            />

            <label
              htmlFor="a-password"
              className="mb-1.5 block text-[13px] font-medium text-dash-soft"
            >
              Password
            </label>
            <div className="relative">
              <input
                id="a-password"
                type={reveal ? "text" : "password"}
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete={signup ? "new-password" : "current-password"}
                aria-invalid={Boolean(error)}
                aria-describedby={signup ? "a-password-hint" : undefined}
                className="dash-field w-full rounded-lg border border-dash-line-strong bg-dash-surface py-2.5 pl-3.5 pr-11 text-[16px] text-dash-ink outline-none transition-colors focus:border-dash-accent"
              />
              <button
                type="button"
                onClick={() => setReveal((v) => !v)}
                aria-label={reveal ? "Hide password" : "Show password"}
                className="absolute inset-y-0 right-0 flex w-11 items-center justify-center rounded-r-lg text-dash-muted transition-colors hover:text-dash-soft"
              >
                {reveal ? <EyeSlashIcon size={17} /> : <EyeIcon size={17} />}
              </button>
            </div>
            {signup && (
              <p id="a-password-hint" className="mt-1.5 text-[12.5px] text-dash-muted">
                At least {MIN_PASSWORD} characters. Length beats punctuation.
              </p>
            )}

            {error && (
              <div role="alert" className="mt-4 rounded-lg bg-dash-danger-soft px-3.5 py-3">
                <p className="text-[13px] font-medium text-dash-danger">
                  {signup ? "Unable to create that account" : "Unable to sign in"}
                </p>
                <p className="mt-0.5 text-[13px] leading-snug text-dash-soft">{error}</p>
              </div>
            )}

            <button
              type="submit"
              disabled={busy}
              className="mt-6 w-full rounded-lg bg-dash-accent px-4 py-3 text-[14.5px] font-medium text-white transition-colors hover:bg-dash-accent-hover disabled:opacity-50"
            >
              {busy
                ? signup
                  ? "Creating your account…"
                  : "Signing in…"
                : signup
                  ? "Create account"
                  : "Sign in"}
            </button>
          </form>

          {restaurant ? (
            <p className="mt-8 text-[12.5px] leading-relaxed text-dash-muted">
              Restaurant access is arranged by DineMate. If you are here to order
              dinner, choose <span className="font-medium">As a customer</span>.
            </p>
          ) : (
            <button
              type="button"
              onClick={() => {
                setSignup((s) => !s);
                setError(null);
              }}
              className="mt-6 text-[13.5px] text-dash-muted underline-offset-2 transition-colors hover:text-dash-ink hover:underline"
            >
              {signup ? "I already have an account" : "I am new here — create an account"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
