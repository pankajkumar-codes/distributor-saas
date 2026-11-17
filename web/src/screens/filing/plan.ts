import { useQuery } from "@tanstack/react-query";

import { api, call } from "../../api/client";
import type { ApiError } from "../../api/errors";
import type { components } from "../../api/schema";

export type Plan = components["schemas"]["PlanOut"];

/** GET /b/{id}/plan: the GST-filing plan and its prices. `free_for_now` is the server's one switch (R1-M9). */
export function usePlan(businessId: string) {
  return useQuery<Plan, ApiError>({
    queryKey: ["b", businessId, "plan"],
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/plan", { params: { path: { business_id: businessId } } })),
    retry: false,
    staleTime: 5 * 60 * 1000,
  });
}
