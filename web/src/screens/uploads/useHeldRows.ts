import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, call } from "../../api/client";
import type { ApiError } from "../../api/errors";
import type { components } from "../../api/schema";

export type Run = components["schemas"]["RunOut"];
export type HeldRow = components["schemas"]["RowOut"];
export type Action = HeldRow["allowed_actions"][number]["action"];

const PAGE = 50;
export const runKey = (businessId: string, runId: string) => ["b", businessId, "runs", runId];

/** GET /b/{id}/runs/{run_id}: the counts, and whether the preview is still open (`staged`). */
export function useRun(businessId: string, runId: string | null | undefined, enabled = true) {
  return useQuery<Run, ApiError>({
    queryKey: runKey(businessId, runId ?? ""),
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/runs/{run_id}", { params: { path: { business_id: businessId, run_id: runId ?? "" } } })),
    enabled: enabled && Boolean(businessId && runId),
  });
}

/** The held rows of a run, a page at a time. A decided row keeps status "held" and carries its `resolution`. */
export function useHeldRows(businessId: string, runId: string, enabled: boolean) {
  return useInfiniteQuery<{ rows: HeldRow[]; has_more: boolean }, ApiError, { rows: HeldRow[]; has_more: boolean }[], unknown[], number>({
    queryKey: [...runKey(businessId, runId), "held-rows"],
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      call(() =>
        api.GET("/api/v1/b/{business_id}/runs/{run_id}/rows", {
          params: { path: { business_id: businessId, run_id: runId }, query: { status: "held", limit: PAGE, offset: pageParam } },
        }),
      ),
    getNextPageParam: (last, all) => (last.has_more ? all.length * PAGE : undefined),
    select: (data) => data.pages,
    enabled: enabled && Boolean(businessId && runId),
  });
}

export type Decision = { rowId: string; action: Action; note: string; value?: string };

/**
 * POST /b/{id}/rows/{row_id}/resolve. One Idempotency-Key per decision: the caller passes the key so a retry of the
 * same decision (after a dropped answer) is the same call, and a new decision has a new key.
 */
export function useDecide(businessId: string, runId: string) {
  const queryClient = useQueryClient();
  const refresh = () => queryClient.invalidateQueries({ queryKey: runKey(businessId, runId) });
  const mutation = useMutation<HeldRow, ApiError, Decision & { key: string }>({
    mutationFn: ({ rowId, action, note, value, key }) =>
      call(() =>
        api.POST("/api/v1/b/{business_id}/rows/{row_id}/resolve", {
          params: { path: { business_id: businessId, row_id: rowId }, header: { "Idempotency-Key": key } },
          body: { action, note, ...(value ? { value } : {}) },
        }),
      ),
    onSuccess: refresh,
    // A refused decision can mean the run was closed or the row already decided; look again either way.
    onError: refresh,
  });
  return mutation;
}
