import { useQuery } from "@tanstack/react-query";

import { api, call } from "../../api/client";
import type { ApiError } from "../../api/errors";
import type { components } from "../../api/schema";

export type ChannelsOut = components["schemas"]["ChannelsOut"];

/** Where the business sells, as chosen at setup. The same cache entry as Settings › Where you sell. */
export function useChannels(businessId: string, enabled = true) {
  return useQuery<ChannelsOut, ApiError>({
    queryKey: ["b", businessId, "channels"],
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/channels", { params: { path: { business_id: businessId } } })),
    enabled: enabled && Boolean(businessId),
  });
}
