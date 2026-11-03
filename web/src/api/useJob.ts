import { useQuery } from "@tanstack/react-query";

import { api, call } from "./client";
import type { ApiError } from "./errors";
import type { components } from "./schema";

export type Job = components["schemas"]["JobOut"];

/** A job stops changing once it is done or failed; `failed_retryable` is the runner's to retry. */
export const finished = (job: Job | undefined) => job?.status === "done" || job?.status === "failed";

/** Poll gaps: 1 s, 2 s, 4 s, then every 5 s, so a quick job shows quickly and a slow one costs little. */
export const pollDelay = (polls: number) => Math.min(1000 * 2 ** polls, 5000);

/**
 * Follows a background job (LLD-0 §3.7, GET /b/{id}/jobs/{job_id}) until it is done or failed.
 * The business's own route: another business's job ID is the server's 404.
 */
export function useJob(businessId: string, jobId: string | null | undefined) {
  return useQuery<Job, ApiError>({
    queryKey: ["b", businessId, "job", jobId],
    queryFn: () =>
      call(() => api.GET("/api/v1/b/{business_id}/jobs/{job_id}", { params: { path: { business_id: businessId, job_id: jobId ?? "" } } })),
    enabled: Boolean(businessId && jobId),
    refetchIntervalInBackground: true, // a hidden tab still finds out the import finished
    // dataUpdateCount is already 1 after the first answer, so the gap after answer n is pollDelay(n - 1).
    refetchInterval: (query) =>
      finished(query.state.data) || query.state.error ? false : pollDelay(Math.max(0, query.state.dataUpdateCount - 1)),
  });
}
