"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import * as api from "@/lib/api";

type AuthState = {
  user: api.User | null;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<api.User>;
  signUp: (email: string, password: string, name?: string) => Promise<api.User>;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

/**
 * The signed-in identity, remembered for the tab.
 *
 * Identity itself lives in httpOnly cookies and is only ever proved by the
 * server: this is a hint, not a credential. It exists because /api/auth/me is a
 * round trip to a remote database, and without it every page load - including
 * every hop between the chat, orders and the dashboard - opened on a "Loading…"
 * screen for the length of that trip. With it the app renders immediately and
 * `me()` confirms in the background; if it disagrees, the hint is dropped.
 *
 * sessionStorage, not localStorage: a shared browser must not carry one
 * person's name into the next person's tab.
 */
const CACHE_KEY = "dm.user";

function remembered(): api.User | null {
  if (typeof sessionStorage === "undefined") return null;
  try {
    const raw = sessionStorage.getItem(CACHE_KEY);
    return raw ? (JSON.parse(raw) as api.User) : null;
  } catch {
    return null;
  }
}

function remember(user: api.User | null): void {
  if (typeof sessionStorage === "undefined") return;
  try {
    if (user) sessionStorage.setItem(CACHE_KEY, JSON.stringify(user));
    else sessionStorage.removeItem(CACHE_KEY);
  } catch {
    /* private mode, or a full quota: the app works without the hint */
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<api.User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Read on the client only: the server render has no sessionStorage, and
    // seeding state from it directly would be a hydration mismatch.
    const cached = remembered();
    if (cached) {
      // Deliberate, and it has to be here: sessionStorage does not exist during
      // the server render, so seeding this in useState would make the client's
      // first render disagree with the HTML it is hydrating.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setUser(cached);
      setLoading(false);
    }

    // A 401 here is the normal signed-out case, not an error worth surfacing.
    api
      .me()
      .then((r) => {
        setUser(r.user);
        remember(r.user);
      })
      .catch(() => {
        setUser(null);
        remember(null);
      })
      .finally(() => setLoading(false));
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    const { user: signedIn } = await api.login(email, password);
    setUser(signedIn);
    remember(signedIn);
    return signedIn;
  }, []);

  const signUp = useCallback(async (email: string, password: string, name?: string) => {
    const { user: created } = await api.register(email, password, name);
    setUser(created);
    remember(created);
    return created;
  }, []);

  const signOut = useCallback(async () => {
    // Cleared first: a signed-out screen must never wait on the network.
    setUser(null);
    remember(null);
    await api.logout().catch(() => undefined);
  }, []);

  const value = useMemo(
    () => ({ user, loading, signIn, signUp, signOut }),
    [user, loading, signIn, signUp, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
