import { useQuery } from "@tanstack/react-query";
import { Navigate } from "react-router-dom";

import { api, call } from "../../api/client";
import type { ApiError } from "../../api/errors";
import { useAuthStatus } from "../../auth/AuthProvider";
import { landingPath } from "../../auth/landing";
import { SigninRedirectNotice } from "./SigninRedirectNotice";

/**
 * "/": the Kartaa landing page is a separate static site that the web server shows at this address for visitors
 * without a session (vite.config.ts in development and preview, demo/nginx.conf in the demo). The app only gets
 * here when a signed-in person (or a stale sign-in hint) asked for "/". A signed-in person goes to their home;
 * anyone else goes to sign-in.
 */
export function RootPage() {
  const status = useAuthStatus();
  if (status === "signed_out") return <Navigate to="/signin" replace />;
  if (status !== "signed_in") return <SigninRedirectNotice status={status} />;
  return <GoHome />;
}

function GoHome() {
  const mine = useQuery<string, ApiError>({
    queryKey: ["root", "landing"],
    queryFn: async () => {
      const me = await call(() => api.GET("/api/v1/me/businesses"));
      return landingPath(me.businesses, me.is_support);
    },
  });
  if (mine.data) return <Navigate to={mine.data} replace />;
  if (mine.error) return <Navigate to="/signin" replace />;
  return (
    <main className="page" aria-busy="true">
      <p>Loading…</p>
    </main>
  );
}
