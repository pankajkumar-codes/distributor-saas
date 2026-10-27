import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { Banner } from "../kit/Banner";
import { Button } from "../kit/Button";

import { onSessionChange, refreshSession, type RefreshResult } from "./session";
import { tokenStore } from "./tokenStore";

type Status = "checking" | "signed_in" | "signed_out" | "unavailable";

const AuthContext = createContext<{ status: Status; retry: () => void }>({ status: "checking", retry: () => {} });

const STATUS: Record<RefreshResult, Status> = { ok: "signed_in", signed_out: "signed_out", unavailable: "unavailable" };

/** On load, asks /auth/refresh whether the cookie still names a session (LLD-1 §11.3). */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>(() => (tokenStore.get() ? "signed_in" : "checking"));

  const check = () => {
    setStatus("checking");
    refreshSession().then((result) => setStatus(STATUS[result]));
  };

  useEffect(() => {
    const stop = onSessionChange((signedIn) => setStatus(signedIn ? "signed_in" : "signed_out"));
    if (!tokenStore.get()) refreshSession().then((result) => setStatus(STATUS[result]));
    return stop;
  }, []);

  return <AuthContext.Provider value={{ status, retry: check }}>{children}</AuthContext.Provider>;
}

export function useAuthStatus(): Status {
  return useContext(AuthContext).status;
}

/** Pages behind sign-in. A signed-out visitor goes to /signin and comes back after. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { status, retry } = useContext(AuthContext);
  const location = useLocation();
  if (status === "unavailable") {
    // Offline or the server is struggling: the session may be fine, so don't sign out.
    return (
      <main className="page">
        <Banner tone="error">We couldn't reach the server. Check your connection and try again.</Banner>
        <Button type="button" onClick={retry}>
          Try again
        </Button>
      </main>
    );
  }
  if (status === "checking") {
    return (
      <main className="page" aria-busy="true">
        <p>Loading…</p>
      </main>
    );
  }
  if (status === "signed_out") {
    // Only the path goes in `next`: it never carries an email or a code.
    return <Navigate to={`/signin?next=${encodeURIComponent(location.pathname)}`} replace />;
  }
  return children;
}

/** Where `next` may send someone: a path on this site, never another origin. */
export function safeNext(next: string | null): string | null {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.includes("\\")) return null;
  return /[\u0000-\u001f\u007f]/.test(next) ? null : next;
}
