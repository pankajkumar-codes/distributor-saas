import { useQuery } from "@tanstack/react-query";

import { api, call } from "./client";
import type { ApiError } from "./errors";
import type { components } from "./schema";

/** States for an address or registration (refdata). 96 (other country) is a place of supply only. */
export function useStateCodes() {
  return useQuery<components["schemas"]["StateCode"][], ApiError>({
    queryKey: ["refdata", "state-codes"],
    queryFn: async () =>
      (await call(() => api.GET("/api/v1/refdata/state-codes"))).states.filter((s) => s.code !== "96"),
    staleTime: Infinity,
  });
}
