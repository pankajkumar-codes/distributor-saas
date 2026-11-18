import { useQuery } from "@tanstack/react-query";

import { api, call } from "../../api/client";
import type { ApiError } from "../../api/errors";
import type { components } from "../../api/schema";

export type CrossCheck = components["schemas"]["CrossCheckOut"];

/** GET /b/{id}/own-invoices/crosscheck (D-059): Excel against PDF, computed on request. Read-only. */
export function useCrosscheck(businessId: string, enabled: boolean) {
  return useQuery<CrossCheck, ApiError>({
    queryKey: ["b", businessId, "own-invoices-crosscheck"],
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/own-invoices/crosscheck", { params: { path: { business_id: businessId } } })),
    enabled: enabled && Boolean(businessId),
  });
}
