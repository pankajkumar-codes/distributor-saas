import { useQuery } from "@tanstack/react-query";

import { api, call } from "../../api/client";
import type { ApiError } from "../../api/errors";

/**
 * GET /b/{id}/returns?fy= (S-2). Typed by hand until the server's PR puts the route in the
 * generated schema; then this becomes `components["schemas"][...]` and the cast below goes.
 */
export type ReturnRow = {
  instance_id: string;
  form: string;
  period: string;
  period_label: string;
  period_start: string;
  period_end: string;
  due_date: string | null;
  due_date_confirmed: boolean;
  due_date_source_url: string | null;
  status: string;
};
export type ReturnsOut = { fy: string; filing_frequency: "monthly" | "quarterly" | null; returns: ReturnRow[] };

type RawGet = (path: string, init: { params: { path: { business_id: string }; query: { fy: string } } }) => Promise<{ data?: ReturnsOut; error?: unknown; response: Response }>;

export function useReturns(businessId: string, fy: string, enabled: boolean) {
  return useQuery<ReturnsOut, ApiError>({
    queryKey: ["b", businessId, "returns", fy],
    queryFn: () =>
      call(() =>
        (api.GET as unknown as RawGet)("/api/v1/b/{business_id}/returns", { params: { path: { business_id: businessId }, query: { fy } } }),
      ),
    enabled,
  });
}
