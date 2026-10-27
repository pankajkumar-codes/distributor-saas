import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { onSessionChange, refreshSession } from "./session";
import { tokenStore } from "./tokenStore";

type Status = "checking" | "signed_in" | "signed_out";

const AuthContext = createContext<Status>("checking");

/** On load, asks /auth/refresh whether the cookie still names a session (LLD-1 §11.3). */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>(() => (tokenStore.get() ? "signed_in" : "checking"));

  useEffect(() => {
    const stop = onSessionChange((signedIn) => setStatus(signedIn ? "signed_in" : "signed_out"));
    if (!tokenStore.get()) {
      refreshSession().then((ok) => setStatus(ok ? "signed_in" : "signed_out"));
    }
    return stop;
  }, []);

  return <AuthContext.Provider value={status}>{children}</AuthContext.Provider>;
}

export function useAuthStatus(): Status {
  return useContext(AuthContext);
}

/** Pages behind sign-in. A signed-out visitor goes to /signin and comes back after. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const status = useAuthStatus();
  const location = useLocation();
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
  return next && next.startsWith("/") && !next.startsWith("//") && !next.includes("\\") ? next : null;
}
