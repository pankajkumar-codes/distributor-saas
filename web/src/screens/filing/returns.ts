import { useInfiniteQuery, useQuery, type InfiniteData } from "@tanstack/react-query";

import { api, call } from "../../api/client";
import type { ApiError } from "../../api/errors";
import type { components } from "../../api/schema";

export type ReturnRow = components["schemas"]["ReturnOut"];
export type ReturnsOut = components["schemas"]["ReturnsOut"];

/** GET /b/{id}/returns?fy= (S-2): the server's periods, due dates and statuses. No `fy` means the server's current financial year. */
export function useReturns(businessId: string, fy: string | undefined, enabled: boolean) {
  return useQuery<ReturnsOut, ApiError>({
    queryKey: ["b", businessId, "returns", fy],
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/returns", { params: { path: { business_id: businessId }, query: { fy } } })),
    enabled,
  });
}

export type ReturnDetail = components["schemas"]["ReturnDetailOut"];
export type SectionName = components["schemas"]["app__modules__filing__api__SectionOut"]["name"];
export type SectionPage = components["schemas"]["B2BPage"] | components["schemas"]["B2CLPage"] | components["schemas"]["B2CSPage"] | components["schemas"]["CDNRPage"] | components["schemas"]["CDNURPage"] | components["schemas"]["HsnB2bPage"] | components["schemas"]["HsnB2cPage"];

/** Everything a return screen holds shares this key prefix, so one reset reloads the lot. */
export const returnKey = (businessId: string, instanceId: string) => ["b", businessId, "return", instanceId] as const;

/** GET /b/{id}/returns/{instance} (R1-M7 S5): a fresh, read-only build of the return. */
export function useReturnDetail(businessId: string, instanceId: string) {
  return useQuery<ReturnDetail, ApiError>({
    queryKey: [...returnKey(businessId, instanceId), "detail"],
    queryFn: () =>
      call(() => api.GET("/api/v1/b/{business_id}/returns/{instance_id}", { params: { path: { business_id: businessId, instance_id: instanceId } } })),
    retry: false,
  });
}

/** One section's rows, 100 at a time. Every page carries the fingerprint of the build it came from. */
export function useSectionRows(businessId: string, instanceId: string, section: SectionName, enabled: boolean) {
  return useInfiniteQuery<SectionPage, ApiError, InfiniteData<SectionPage>, readonly unknown[], string | undefined>({
    queryKey: [...returnKey(businessId, instanceId), "section", section],
    initialPageParam: undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    queryFn: ({ pageParam }) =>
      call(() =>
        api.GET("/api/v1/b/{business_id}/returns/{instance_id}/sections/{section}", {
          params: { path: { business_id: businessId, instance_id: instanceId, section }, query: { cursor: pageParam } },
        }),
      ) as Promise<SectionPage>,
    enabled,
    retry: false,
  });
}
