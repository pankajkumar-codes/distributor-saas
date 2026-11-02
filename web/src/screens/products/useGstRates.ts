import { useQuery } from "@tanstack/react-query";

import { api, call } from "../../api/client";
import type { ApiError } from "../../api/errors";

/** The GST rates a product may take on a date (refdata gst.rate_values): the list, never a suggestion. */
export function useGstRates(on: string, enabled: boolean) {
  return useQuery<string[], ApiError>({
    queryKey: ["refdata", "gst-rates", on],
    queryFn: async () => (await call(() => api.GET("/api/v1/refdata/gst-rates", { params: { query: { on } } }))).rates,
    enabled: enabled && /^\d{4}-\d{2}-\d{2}$/.test(on),
    staleTime: Infinity,
  });
}
