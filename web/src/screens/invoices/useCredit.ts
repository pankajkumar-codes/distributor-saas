import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, call } from "../../api/client";
import type { ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import type { Document } from "./useFinalize";

export type CreditState = components["schemas"]["CreditStateOut"];
export type CreditNoteIn = components["schemas"]["CreditNoteIn"];

/** What is left to credit on an issued invoice, line by line, and the notes made against it so far (#456). */
export function useCreditState(businessId: string, documentId: string, enabled = true) {
  return useQuery<CreditState, ApiError>({
    queryKey: ["b", businessId, "document", documentId, "credit"],
    queryFn: () =>
      call(() =>
        api.GET("/api/v1/b/{business_id}/documents/{document_id}/credit", { params: { path: { business_id: businessId, document_id: documentId } } }),
      ),
    enabled: Boolean(businessId && documentId && enabled),
  });
}

/** Issues a credit note against the invoice. One key per form fill, so a retry gives the same note. */
export function useCreateCreditNote(businessId: string, documentId: string, key: () => string, onDone: (note: Document) => void) {
  const queryClient = useQueryClient();
  return useMutation<Document, ApiError, CreditNoteIn>({
    mutationFn: (body) =>
      call(() =>
        api.POST("/api/v1/b/{business_id}/documents/{document_id}/credit-notes", {
          params: { path: { business_id: businessId, document_id: documentId }, header: { "Idempotency-Key": key() } },
          body,
        }),
      ),
    onSuccess: (note) => {
      queryClient.invalidateQueries({ queryKey: ["b", businessId, "document", documentId] });
      queryClient.invalidateQueries({ queryKey: ["b", businessId, "drafts"] }); // the issued list sits under drafts
      queryClient.invalidateQueries({ queryKey: ["b", businessId, "stock"] });
      onDone(note);
    },
  });
}

export type CancelIn = components["schemas"]["CancelIn"];

/** Cancels the invoice (#456). One key per form fill, so a retry cancels once. */
export function useCancelInvoice(businessId: string, documentId: string, key: () => string, onDone: (doc: Document) => void) {
  const queryClient = useQueryClient();
  return useMutation<Document, ApiError, CancelIn>({
    mutationFn: (body) =>
      call(() =>
        api.POST("/api/v1/b/{business_id}/documents/{document_id}/cancel", {
          params: { path: { business_id: businessId, document_id: documentId }, header: { "Idempotency-Key": key() } },
          body,
        }),
      ),
    onSuccess: (doc) => {
      queryClient.invalidateQueries({ queryKey: ["b", businessId, "document", documentId] });
      queryClient.invalidateQueries({ queryKey: ["b", businessId, "drafts"] });
      queryClient.invalidateQueries({ queryKey: ["b", businessId, "stock"] });
      onDone(doc);
    },
  });
}
