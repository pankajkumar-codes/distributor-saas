import { useQuery } from "@tanstack/react-query";

import { api, call } from "../api/client";
import type { ApiError } from "../api/errors";
import type { Membership } from "./landing";

export const SUPPORT_ROLE = "support";

/**
 * The businesses this user can open. A member gets their memberships. Support staff have
 * none (AC2-14), so for them the businesses with a live grant are asked for: each comes back
 * with role "support" and the grant's end. The server checks the grant on every request.
 */
export function useMyBusinesses() {
  return useQuery<Membership[], ApiError>({
    queryKey: ["me", "businesses"],
    queryFn: async () => {
      const mine = await call(() => api.GET("/api/v1/me/businesses"));
      if (!mine.is_support) return mine.businesses;
      const { grants } = await call(() => api.GET("/api/v1/support/grants"));
      return grants.map((g) => ({
        business_id: g.business_id,
        display_name: g.business_name,
        gstin: null,
        role: SUPPORT_ROLE,
        support_ends_at: g.expires_at,
      }));
    },
  });
}
