import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

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

/** The query for one finalized document, shared by the page and by the PDF download, which reads it again for a fresh link. */
export const documentQuery = (businessId: string, documentId: string) => ({
  queryKey: ["b", businessId, "document", documentId],
  queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/documents/{document_id}", { params: { path: { business_id: businessId, document_id: documentId } } })),
});

/**
 * One finalized document with where its PDF stands. While the PDF is queued or rendering the page looks again
 * every few seconds, so a reload or a second visit picks up the same job.
 */
export function useDocument(businessId: string, documentId: string) {
  return useQuery<DocumentDetail, ApiError>({
    ...documentQuery(businessId, documentId),
    enabled: Boolean(businessId && documentId),
    refetchInterval: (q) => (q.state.status === "success" && (q.state.data?.pdf.status === "queued" || q.state.data?.pdf.status === "rendering") ? 2000 : false),
  });
}

/** How often a Download press looks again while the PDF is being made, and for how long at most. The server says failed on its own once the renderer gives up. */
export const PDF_POLL_MS = 1500;
const PDF_WAIT_MS = 3 * 60_000;

/**
 * Download PDF (#422): asks for the document's PDF (the same job unless the last attempt failed), waits while it is queued
 * or rendering, then reads the document once more for a link signed just now (links last a minute) and starts the
 * download from it. Resolves to the link it used, or null if the PDF failed or the wait ran out; the page shows the
 * document's own PDF state in either case. `alive` stops the wait when the page goes away.
 */
export async function downloadDocumentPdf(
  queryClient: QueryClient,
  businessId: string,
  documentId: string,
  ask: () => Promise<unknown>,
  alive: () => boolean,
  save: (url: string) => void = saveUrl,
): Promise<string | null> {
  await ask();
  const started = Date.now();
  while (alive()) {
    const d = await queryClient.fetchQuery<DocumentDetail, ApiError>({ ...documentQuery(businessId, documentId), staleTime: 0 });
    if (d.pdf.status === "ready" && d.pdf.url) {
      if (alive()) save(d.pdf.url);
      return d.pdf.url;
    }
    if (d.pdf.status === "failed" || d.pdf.status === "none" || Date.now() - started > PDF_WAIT_MS) return null;
    await new Promise((r) => setTimeout(r, PDF_POLL_MS));
  }
  return null;
}

/** Starts a browser download from a signed link. The link's own Content-Disposition names the file (practice-invoice.pdf). */
export function saveUrl(url: string) {
  const a = Object.assign(document.createElement("a"), { href: url, rel: "noopener", hidden: true });
  a.setAttribute("download", "");
  document.body.append(a);
  a.click();
  a.remove();
}
