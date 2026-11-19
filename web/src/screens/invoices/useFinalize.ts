import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, call } from "../../api/client";
import type { ApiError } from "../../api/errors";
import type { components } from "../../api/schema";

export type Document = components["schemas"]["DocumentOut"];
type PdfRef = components["schemas"]["DocumentPdfRef"];
export type DocumentDetail = components["schemas"]["DocumentDetailOut"];

/**
 * Issues the saved draft as a document. One key per draft and version, so a retry gives the same document.
 * `mutate({ draftId, version })` finalizes a draft that was only just saved (the page's own ids are then out of date).
 */
export function useFinalize(businessId: string, draftId: string, version: number | undefined, key: string, onDone: (doc: Document) => void) {
  const queryClient = useQueryClient();
  return useMutation<Document, ApiError, { draftId: string; version: number } | void>({
    mutationFn: (saved) => {
      const id = saved ? saved.draftId : draftId;
      const v = saved ? saved.version : version;
      return call(() =>
        api.POST("/api/v1/b/{business_id}/drafts/{draft_id}/finalize", {
          params: { path: { business_id: businessId, draft_id: id }, header: { "If-Match": String(v), "Idempotency-Key": saved ? `finalize-${id}-${v}` : key } },
        }),
      );
    },
    onSuccess: (doc) => {
      onDone(doc);
      queryClient.invalidateQueries({ queryKey: ["b", businessId, "drafts"] });
      queryClient.invalidateQueries({ queryKey: ["b", businessId, "stock"] });
      queryClient.invalidateQueries({ queryKey: ["b", businessId, "invoicing-plan"] });
    },
  });
}

/** Asks for the document's PDF; the page then watches the document, which carries where the PDF stands. */
export function useDocumentPdfRequest(businessId: string, documentId: string, onAsked: () => void) {
  return useMutation<PdfRef, ApiError>({
    mutationFn: () => call(() => api.POST("/api/v1/b/{business_id}/documents/{document_id}/pdf", { params: { path: { business_id: businessId, document_id: documentId } } })),
    onSuccess: onAsked,
  });
}

/**
 * One finalized document with where its PDF stands. While the PDF is queued or rendering the page looks again
 * every few seconds, so a reload or a second visit picks up the same job.
 */
export function useDocument(businessId: string, documentId: string) {
  return useQuery<DocumentDetail, ApiError>({
    queryKey: ["b", businessId, "document", documentId],
    enabled: Boolean(businessId && documentId),
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/documents/{document_id}", { params: { path: { business_id: businessId, document_id: documentId } } })),
    refetchInterval: (q) => (q.state.status === "success" && (q.state.data?.pdf.status === "queued" || q.state.data?.pdf.status === "rendering") ? 2000 : false),
  });
}
