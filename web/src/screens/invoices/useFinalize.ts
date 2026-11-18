import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, call } from "../../api/client";
import type { ApiError } from "../../api/errors";
import { pollDelay } from "../../api/useJob";
import type { components } from "../../api/schema";

export type Document = components["schemas"]["DocumentOut"];
type PdfRef = components["schemas"]["DocumentPdfRef"];
type PdfOut = components["schemas"]["PreviewOut"];

/** Issues the saved draft as a document. One key per draft and version, so a retry gives the same document. */
export function useFinalize(businessId: string, draftId: string, version: number | undefined, key: string) {
  const queryClient = useQueryClient();
  return useMutation<Document, ApiError>({
    mutationFn: () =>
      call(() =>
        api.POST("/api/v1/b/{business_id}/drafts/{draft_id}/finalize", {
          params: { path: { business_id: businessId, draft_id: draftId }, header: { "If-Match": String(version), "Idempotency-Key": key } },
        }),
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["b", businessId, "drafts"] });
      queryClient.invalidateQueries({ queryKey: ["b", businessId, "stock"] });
      queryClient.invalidateQueries({ queryKey: ["b", businessId, "invoicing-plan"] });
    },
  });
}

/** The finalized document's PDF: `start` queues it, then the status is polled until it is ready or failed. */
export function useDocumentPdf(businessId: string, documentId: string) {
  const path = { business_id: businessId, document_id: documentId };
  const start = useMutation<PdfRef, ApiError>({
    mutationFn: () => call(() => api.POST("/api/v1/b/{business_id}/documents/{document_id}/pdf", { params: { path } })),
  });
  const jobId = start.data?.job_id;
  const status = useQuery<PdfOut, ApiError>({
    queryKey: ["b", businessId, "document", documentId, "pdf", jobId, start.data?.attempt],
    enabled: Boolean(jobId),
    gcTime: 0, // the link is good for 60 seconds, so a later visit asks again
    retry: false,
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/documents/{document_id}/pdf/{job_id}", { params: { path: { ...path, job_id: jobId ?? "" } } })),
    refetchIntervalInBackground: true,
    refetchInterval: (q) => (q.state.error || q.state.data?.status === "ready" || q.state.data?.status === "failed" ? false : pollDelay(Math.max(0, q.state.dataUpdateCount - 1))),
  });
  return { start, status };
}
