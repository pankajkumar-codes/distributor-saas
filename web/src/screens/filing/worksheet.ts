import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, call } from "../../api/client";
import type { ApiError } from "../../api/errors";
import type { components } from "../../api/schema";

export type Worksheet = components["schemas"]["WorksheetOut"];
export type Outward = components["schemas"]["OutwardOut"];
export type ExcelOut = components["schemas"]["ExcelOut"];
export type EntriesOut = components["schemas"]["EntriesOut"];

const path = (businessId: string, instanceId: string) => ({ business_id: businessId, instance_id: instanceId });
export const worksheetKey = (businessId: string, instanceId: string) => ["b", businessId, "return", instanceId, "worksheet"] as const;

/** GET …/worksheet: the latest build, what was typed, and whether the GSTR-1 has changed since. */
export function useWorksheet(businessId: string, instanceId: string, enabled = true) {
  return useQuery<Worksheet, ApiError>({
    queryKey: worksheetKey(businessId, instanceId),
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/returns/{instance_id}/worksheet", { params: { path: path(businessId, instanceId) } })),
    enabled,
    retry: false,
  });
}

/** POST …/worksheet/build: the next version of the outward figures. */
export function useBuildWorksheet(businessId: string, instanceId: string) {
  const queryClient = useQueryClient();
  return useMutation<Outward, ApiError>({
    mutationFn: () => call(() => api.POST("/api/v1/b/{business_id}/returns/{instance_id}/worksheet/build", { params: { path: path(businessId, instanceId) } })),
    onSettled: () => queryClient.invalidateQueries({ queryKey: worksheetKey(businessId, instanceId) }),
  });
}

/** PUT …/worksheet/entries: the whole set of what the seller typed, against the save it was based on. */
export function useSaveEntries(businessId: string, instanceId: string) {
  const queryClient = useQueryClient();
  return useMutation<EntriesOut, ApiError, { entries: Record<string, string>; based_on_seq: number | null }>({
    mutationFn: (body) => call(() => api.PUT("/api/v1/b/{business_id}/returns/{instance_id}/worksheet/entries", { params: { path: path(businessId, instanceId) }, body })),
    onSettled: () => queryClient.invalidateQueries({ queryKey: worksheetKey(businessId, instanceId) }),
  });
}

/** GET …/worksheet/excel: the file as it is now, as a 60-second link. */
export function useWorksheetExcel(businessId: string, instanceId: string) {
  return useMutation<ExcelOut, ApiError>({
    mutationFn: () => call(() => api.GET("/api/v1/b/{business_id}/returns/{instance_id}/worksheet/excel", { params: { path: path(businessId, instanceId) } })),
  });
}
