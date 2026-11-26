import { useQuery } from "@tanstack/react-query";

import { api, call } from "../api/client";
import type { ApiError } from "../api/errors";
import type { components } from "../api/schema";

export type NumberingOut = components["schemas"]["NumberingOut"];

export const numberingKey = (businessId: string) => ["b", businessId, "numbering"];

/** The business's numbering settings (#461), shared by Settings, the top bar and the invoice page. */
export function useNumbering(businessId: string | undefined) {
  return useQuery<NumberingOut, ApiError>({
    queryKey: numberingKey(businessId ?? ""),
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/numbering", { params: { path: { business_id: businessId! } } })),
    enabled: !!businessId,
    staleTime: 60_000,
  });
}

/**
 * Whether this business issues practice documents (#477): true until its owner turns on live numbering. While the
 * settings are loading or can't be read it says practice, which only adds a label; the server decides the number.
 */
export function usePracticeMode(businessId: string | undefined): { practice: boolean; liveAvailable: boolean } {
  const n = useNumbering(businessId).data;
  return { practice: !n?.live, liveAvailable: !!n?.live_available };
}
