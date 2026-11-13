import { useQuery } from "@tanstack/react-query";

import { api, call } from "../../api/client";
import type { ApiError } from "../../api/errors";
import type { components } from "../../api/schema";

export type ReturnRow = components["schemas"]["ReturnOut"];
export type ReturnsOut = components["schemas"]["ReturnsOut"];

/** GET /b/{id}/returns?fy= (S-2): the server's periods, due dates and statuses. */
export function useReturns(businessId: string, fy: string, enabled: boolean) {
  return useQuery<ReturnsOut, ApiError>({
    queryKey: ["b", businessId, "returns", fy],
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/returns", { params: { path: { business_id: businessId }, query: { fy } } })),
    enabled,
  });
}
