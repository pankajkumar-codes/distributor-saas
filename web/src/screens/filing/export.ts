import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, call } from "../../api/client";
import type { ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { returnKey } from "./returns";

export type ExportStatus = components["schemas"]["ExportStatusOut"];
export type Changes = components["schemas"]["ChangesOut"];
export type FiledOut = components["schemas"]["FiledOut"];

const path = (businessId: string, instanceId: string) => ({ business_id: businessId, instance_id: instanceId });

/** Everything about a return, and the list it sits in, is read again after a change. */
function useReload(businessId: string, instanceId: string) {
  const queryClient = useQueryClient();
  return () => Promise.all([queryClient.invalidateQueries({ queryKey: returnKey(businessId, instanceId) }), queryClient.invalidateQueries({ queryKey: ["b", businessId, "returns"] })]);
}

/** POST …/check-acceptances: accept the warnings of one check as they are shown now, with a note. */
export function useAccept(businessId: string, instanceId: string) {
  const reload = useReload(businessId, instanceId);
  return useMutation<unknown, ApiError, { check_code: string; note: string }>({
    mutationFn: (body) => call(() => api.POST("/api/v1/b/{business_id}/returns/{instance_id}/check-acceptances", { params: { path: path(businessId, instanceId) }, body })),
    onSuccess: reload,
  });
}

/** POST …/exports: queue the file; the answer is the job to watch. */
export function useStartExport(businessId: string, instanceId: string) {
  return useMutation<{ job_id: string }, ApiError>({
    mutationFn: () => call(() => api.POST("/api/v1/b/{business_id}/returns/{instance_id}/exports", { params: { path: path(businessId, instanceId) } })),
  });
}

/** GET …/exports/{job}: asked again every 1.5 seconds while the file is being made. */
export function useExportStatus(businessId: string, instanceId: string, jobId: string | null) {
  return useQuery<ExportStatus, ApiError>({
    queryKey: [...returnKey(businessId, instanceId), "export", jobId],
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/returns/{instance_id}/exports/{job_id}", { params: { path: { ...path(businessId, instanceId), job_id: jobId ?? "" } } })),
    enabled: jobId !== null,
    refetchInterval: (q) => (q.state.data?.status === "preparing" ? 1500 : false),
    retry: false,
    gcTime: 0, // the links last 60 seconds: never show old ones from the cache
  });
}

/** GET …/changes: what differs between the return now and the file the user took, by document number. */
export function useChanges(businessId: string, instanceId: string, enabled: boolean) {
  return useQuery<Changes, ApiError>({
    queryKey: [...returnKey(businessId, instanceId), "changes"],
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/returns/{instance_id}/changes", { params: { path: path(businessId, instanceId) } })),
    enabled,
    retry: false,
  });
}

/** POST …/filed: record the filing and lock the return. A reason confirms that what was filed differs from our file. */
export function useMarkFiled(businessId: string, instanceId: string) {
  const reload = useReload(businessId, instanceId);
  return useMutation<FiledOut, ApiError, { filed_on: string; arn: string; reason?: string }>({
    mutationFn: ({ filed_on, arn, reason }) =>
      call(() =>
        api.POST("/api/v1/b/{business_id}/returns/{instance_id}/filed", {
          params: { path: path(businessId, instanceId) },
          body: { filed_on, arn, accept_changed: reason === undefined ? null : { reason } },
        }),
      ),
    onSuccess: reload,
  });
}

/** GET …/lock-file: the file kept with the lock, with fresh 60-second links. */
export function useLockFile(businessId: string, instanceId: string) {
  return useMutation<ExportStatus, ApiError>({
    mutationFn: () => call(() => api.GET("/api/v1/b/{business_id}/returns/{instance_id}/lock-file", { params: { path: path(businessId, instanceId) } })),
  });
}

/** POST …/unlock: owner only, with a reason. */
export function useUnlock(businessId: string, instanceId: string) {
  const reload = useReload(businessId, instanceId);
  return useMutation<unknown, ApiError, string>({
    mutationFn: (reason) => call(() => api.POST("/api/v1/b/{business_id}/returns/{instance_id}/unlock", { params: { path: path(businessId, instanceId) }, body: { reason } })),
    onSuccess: reload,
  });
}

/** POST …/completed: the user filed this return on the portal outside Kartaa (#424). Any form, GSTR-3B included. */
export function useMarkCompleted(businessId: string, instanceId: string) {
  const reload = useReload(businessId, instanceId);
  return useMutation<unknown, ApiError, { filed_on: string; arn: string }>({
    mutationFn: (body) => call(() => api.POST("/api/v1/b/{business_id}/returns/{instance_id}/completed", { params: { path: path(businessId, instanceId) }, body })),
    onSuccess: reload,
  });
}
