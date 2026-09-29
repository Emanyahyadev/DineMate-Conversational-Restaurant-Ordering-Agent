"use client";

import { type ReactNode } from "react";

import AuthPanel from "@/components/AuthPanel";
import { useAuth } from "@/components/AuthProvider";

/**
 * Everything behind DineMate needs an account: memory and order history are
 * per-customer, and a shared browser must never serve one person another's
 * allergy profile (AUTH_SPEC section 1).
 *
 * The form itself is AuthPanel, shared with /kitchen so there is one front door
 * for both audiences rather than a screen each.
 */
export default function AuthGate({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();

  if (user) return <>{children}</>;

  // Still confirming. Shown rather than the form, because flashing a sign-in
  // screen at somebody who is already signed in reads as being logged out.
  // AuthProvider caches the session per tab, so this is a cold tab only.
  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center bg-dash-bg">
        <p className="text-[14px] text-dash-muted">Loading…</p>
      </div>
    );
  }

  return <AuthPanel initialAudience="customer" />;
}
