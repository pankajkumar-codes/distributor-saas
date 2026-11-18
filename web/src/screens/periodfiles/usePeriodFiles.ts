import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, call } from "../../api/client";
import type { ApiError } from "../../api/errors";
import type { components } from "../../api/schema";

export type PeriodExport = components["schemas"]["PeriodExportOut"];
export type Profile = components["schemas"]["FilingProfileOut"];
type Kind = components["schemas"]["PeriodFilesIn"]["kind"];

export const periodFilesKey = (businessId: string) => ["b", businessId, "period-files"] as const;

export function useFilingProfile(businessId: string, enabled: boolean) {
  return useQuery<Profile, ApiError>({
    queryKey: ["b", businessId, "filing-profile"],
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/filing-profile", { params: { path: { business_id: businessId } } })),
    enabled,
  });
}

export function useExports(businessId: string, enabled: boolean) {
  return useQuery<PeriodExport[], ApiError>({
    queryKey: periodFilesKey(businessId),
    queryFn: async () => (await call(() => api.GET("/api/v1/b/{business_id}/period-files", { params: { path: { business_id: businessId } } }))).exports,
    enabled,
  });
}

/** POST …/period-files: the same data gives the same export, so pressing twice is safe. The answer carries the links. */
export function useMakeFiles(businessId: string) {
  const queryClient = useQueryClient();
  return useMutation<PeriodExport, ApiError, { kind: Kind; start: string }>({
    mutationFn: (body) => call(() => api.POST("/api/v1/b/{business_id}/period-files", { params: { path: { business_id: businessId } }, body })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: periodFilesKey(businessId) }),
  });
}

/** GET …/period-files/{id}: fresh 60-second links for a file made earlier. */
export function useFreshLinks(businessId: string) {
  return useMutation<PeriodExport, ApiError, string>({
    mutationFn: (id) => call(() => api.GET("/api/v1/b/{business_id}/period-files/{export_id}", { params: { path: { business_id: businessId, export_id: id } } })),
  });
}
