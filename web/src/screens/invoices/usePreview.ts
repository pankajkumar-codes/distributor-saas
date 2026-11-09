import { useMutation, useQuery } from "@tanstack/react-query";

import { api, call } from "../../api/client";
import type { ApiError } from "../../api/errors";
import { pollDelay } from "../../api/useJob";
import type { components } from "../../api/schema";

type Ref = components["schemas"]["PreviewRef"];
type Out = components["schemas"]["PreviewOut"];

/**
 * The draft's PDF preview: `start` queues one job for the saved version (the same version
 * always gives the same job), then the status is polled until it is ready or failed.
 */
export function usePreview(businessId: string, draftId: string) {
  const path = { business_id: businessId, draft_id: draftId };
  const start = useMutation<Ref, ApiError>({
    mutationFn: () => call(() => api.POST("/api/v1/b/{business_id}/drafts/{draft_id}/preview", { params: { path } })),
  });
  const jobId = start.data?.job_id;
  const status = useQuery<Out, ApiError>({
    queryKey: ["b", businessId, "draft", draftId, "preview", jobId],
    enabled: Boolean(jobId),
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/drafts/{draft_id}/preview/{job_id}", { params: { path: { ...path, job_id: jobId ?? "" } } })),
    refetchIntervalInBackground: true,
    refetchInterval: (q) => (q.state.error || q.state.data?.status === "ready" || q.state.data?.status === "failed" ? false : pollDelay(Math.max(0, q.state.dataUpdateCount - 1))),
  });
  return { start, status, forVersion: start.data?.draft_version };
}
