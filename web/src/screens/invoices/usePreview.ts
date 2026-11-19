import { useMutation, useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { api, call } from "../../api/client";
import type { ApiError } from "../../api/errors";
import { pollDelay } from "../../api/useJob";
import type { components } from "../../api/schema";

type Ref = components["schemas"]["PreviewRef"];
type Out = components["schemas"]["PreviewOut"];

// About two minutes of polling (1, 2, 4 s, then 5 s apart). A preview that is not ready by then is not going to be:
// say so, instead of polling for ever (past the 5 minute access token) and showing "Preparing" for as long as the tab lives.
export const MAX_POLLS = 26;

/**
 * The draft's PDF preview: `start` queues one job for the saved version (the same version
 * always gives the same job), then the status is polled until it is ready or failed.
 */
export function usePreview(businessId: string, draftId: string) {
  const path = { business_id: businessId, draft_id: draftId };
  const [attempt, setAttempt] = useState(0); // a new press starts a new count of polls
  const polls = useRef(0); // answers received for the current attempt
  const start = useMutation<Ref, ApiError>({
    mutationFn: () => call(() => api.POST("/api/v1/b/{business_id}/drafts/{draft_id}/preview", { params: { path } })),
    onSuccess: () => {
      polls.current = 0;
      setAttempt((n) => n + 1);
    },
  });
  const jobId = start.data?.job_id;
  const status = useQuery<Out, ApiError>({
    queryKey: ["b", businessId, "draft", draftId, "preview", jobId, attempt],
    enabled: Boolean(jobId),
    queryFn: async () => {
      const out = await call(() => api.GET("/api/v1/b/{business_id}/drafts/{draft_id}/preview/{job_id}", { params: { path: { ...path, job_id: jobId ?? "" } } }));
      polls.current += 1;
      return out;
    },
    // A hidden tab stops; coming back to the tab polls again at once.
    refetchInterval: (q) =>
      q.state.error || q.state.data?.status === "ready" || q.state.data?.status === "failed" || q.state.dataUpdateCount >= MAX_POLLS
        ? false
        : pollDelay(Math.max(0, q.state.dataUpdateCount - 1)),
  });
  // Reading dataUpdatedAt makes every answer re-render, even one identical to the last, so the count below is seen.
  void status.dataUpdatedAt;
  const pending = status.data !== undefined && status.data.status !== "ready" && status.data.status !== "failed";
  return { start, status, forVersion: start.data?.draft_version, timedOut: pending && polls.current >= MAX_POLLS };
}
