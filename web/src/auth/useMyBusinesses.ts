import { useQuery } from "@tanstack/react-query";

import { api, call } from "../api/client";
import type { ApiError } from "../api/errors";
import type { Membership } from "./landing";

export function useMyBusinesses() {
  return useQuery<Membership[], ApiError>({
    queryKey: ["me", "businesses"],
    queryFn: async () => (await call(() => api.GET("/api/v1/me/businesses"))).businesses,
  });
}
