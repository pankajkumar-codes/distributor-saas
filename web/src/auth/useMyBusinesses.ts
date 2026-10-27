import { useQuery } from "@tanstack/react-query";

import { api, call } from "../api/client";
import type { ApiError } from "../api/errors";
import type { Membership } from "./landing";

// Hand-typed until /me/businesses gets a response model (S1-d2).
export function useMyBusinesses() {
  return useQuery<Membership[], ApiError>({
    queryKey: ["me", "businesses"],
    queryFn: async () => {
      const body = (await call(() => api.GET("/api/v1/me/businesses"))) as { businesses: Membership[] };
      return body.businesses;
    },
  });
}
