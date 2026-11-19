import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api, call } from "../../api/client";
import type { ApiError } from "../../api/errors";
import { pollDelay } from "../../api/useJob";
import type { components } from "../../api/schema";

type Ref = components["schemas"]["PreviewRef"];
type Out = components["schemas"]["PreviewOut"];

/** How long "Preparing" may show before the page says it is slow and offers Try again. */
export const PREVIEW_SLOW_MS = 30_000;

/** idle: nothing asked yet. ended: the session is over. failed: the PDF could not be made. error: the request itself failed. */
export type PreviewState = "idle" | "preparing" | "ready" | "slow" | "ended" | "failed" | "error";

/** A refused session: a 401 that a refresh could not settle. */
const sessionEnded = (e: ApiError | null | undefined) => Boolean(e) && (e?.status === 401 || e?.code === "session_invalid");

/**
 * The draft's PDF preview: `start` queues one job for the saved version (the same version
 * always gives the same job), then the status is polled until it is ready or failed.
 * Every call goes through `call`, so an expired access token is refreshed once and retried; what is left is a
 * session that has really ended (`ended`), or an error, and the page says which instead of staying on "Preparing".
 */
export function usePreview(businessId: string, draftId: string) {
  const path = { business_id: businessId, draft_id: draftId };
  const [slow, setSlow] = useState(false);
  const start = useMutation<Ref, ApiError>({
    mutationFn: () => call(() => api.POST("/api/v1/b/{business_id}/drafts/{draft_id}/preview", { params: { path } })),
    onMutate: () => setSlow(false),
  });
  const jobId = start.data?.job_id;
  const status = useQuery<Out, ApiError>({
    queryKey: ["b", businessId, "draft", draftId, "preview", jobId],
    enabled: Boolean(jobId),
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/drafts/{draft_id}/preview/{job_id}", { params: { path: { ...path, job_id: jobId ?? "" } } })),
    refetchIntervalInBackground: true,
    refetchInterval: (q) => (q.state.error || q.state.data?.status === "ready" || q.state.data?.status === "failed" ? false : pollDelay(Math.max(0, q.state.dataUpdateCount - 1))),
  });

  const done = status.data?.status === "ready" || status.data?.status === "failed";
  const waiting = Boolean(jobId) && !done && !status.error;
  const startedAt = start.submittedAt;
  useEffect(() => {
    if (!waiting) return;
    const left = Math.max(0, PREVIEW_SLOW_MS - (Date.now() - startedAt));
    const timer = setTimeout(() => setSlow(true), left);
    return () => clearTimeout(timer);
  }, [waiting, startedAt]);

  const error = start.error ?? status.error ?? null;
  let state: PreviewState = "idle";
  if (sessionEnded(error)) state = "ended";
  else if (error) state = "error";
  else if (status.data?.status === "ready") state = "ready";
  else if (status.data?.status === "failed") state = "failed";
  else if (start.isPending || jobId) state = slow ? "slow" : "preparing";

  /** Ask again: the same saved version gives the same job, so this only looks again or starts what never started. */
  const retry = () => {
    setSlow(false);
    start.mutate(undefined, { onSuccess: () => void status.refetch() });
  };
  return { start, status, state, error, retry, forVersion: start.data?.draft_version };
}
