import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef } from "react";

import { api, call } from "../../api/client";
import type { ApiError } from "../../api/errors";
import { uploadTo } from "../../api/upload";
import { pollDelay } from "../../api/useJob";
import type { components } from "../../api/schema";

export type PurchaseFile = components["schemas"]["PurchaseFileOut"];
export type Draft = components["schemas"]["PurchaseDraftOut"];
export type ConfirmIn = components["schemas"]["PurchaseConfirmIn"];
export type Confirmed = components["schemas"]["PurchaseConfirmedOut"];

export const purchasesKey = (businessId: string) => ["b", businessId, "purchases"];
const POLL_GIVE_UP_MS = 10 * 60 * 1000;
export const fileSettled = (f: PurchaseFile | undefined) => f?.status === "read" || f?.status === "rejected";

/** The business's own profile: the type it chose (or not yet) and the version a change must quote. */
export function useProfile(businessId: string) {
  return useQuery<components["schemas"]["ProfileOut"], ApiError>({
    queryKey: ["b", businessId, "profile"],
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/profile", { params: { path: { business_id: businessId } } })),
    enabled: Boolean(businessId),
  });
}

/** Saves the business type (distributor or retail) with PATCH /profile, as Business setup does. */
export function useChooseBusinessType(businessId: string) {
  const queryClient = useQueryClient();
  return useMutation<unknown, ApiError, { type: "distributor" | "retail"; version: number }>({
    mutationFn: ({ type, version }) =>
      call(() =>
        api.PATCH("/api/v1/b/{business_id}/profile", {
          params: { path: { business_id: businessId }, header: { "If-Match": String(version) } },
          body: { business_type: type },
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["b", businessId, "profile"] }),
  });
}

/** The recent purchase files, newest first; while one is still being read the list looks again every few seconds. */
export function usePurchaseFiles(businessId: string, enabled = true) {
  return useQuery<PurchaseFile[], ApiError>({
    queryKey: [...purchasesKey(businessId), "files"],
    queryFn: async () => (await call(() => api.GET("/api/v1/b/{business_id}/purchase-files", { params: { path: { business_id: businessId } } }))).files,
    enabled: enabled && Boolean(businessId),
    refetchInterval: (q) =>
      q.state.data?.some((f) => !fileSettled(f) && Date.now() - Date.parse(f.created_at) < POLL_GIVE_UP_MS) ? pollDelay(2) : false,
  });
}

/** Drafts still waiting for the business to confirm or discard them. */
export function useOpenDrafts(businessId: string, enabled = true) {
  return useQuery<Draft[], ApiError>({
    queryKey: [...purchasesKey(businessId), "drafts"],
    queryFn: async () =>
      (await call(() => api.GET("/api/v1/b/{business_id}/purchase-drafts", { params: { path: { business_id: businessId }, query: { open_only: true } } }))).drafts,
    enabled: enabled && Boolean(businessId),
  });
}

export function useDraft(businessId: string, draftId: string) {
  return useQuery<Draft, ApiError>({
    queryKey: [...purchasesKey(businessId), "draft", draftId],
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/purchase-drafts/{draft_id}", { params: { path: { business_id: businessId, draft_id: draftId } } })),
    enabled: Boolean(businessId && draftId),
  });
}

/** Start, send to storage, complete. One Idempotency-Key per chosen file; a failed send rotates it. */
export function useSendPurchaseFile(businessId: string) {
  const queryClient = useQueryClient();
  const key = useRef(crypto.randomUUID());
  return useMutation<string, ApiError, File>({
    mutationFn: async (file) => {
      const started = await call(() =>
        api.POST("/api/v1/b/{business_id}/purchase-files", {
          params: { path: { business_id: businessId }, header: { "Idempotency-Key": key.current } },
          body: { file_name: file.name, size_bytes: file.size },
        }),
      );
      try {
        await uploadTo(started.upload, file);
      } catch (e) {
        key.current = crypto.randomUUID();
        throw e;
      }
      await call(() =>
        api.POST("/api/v1/b/{business_id}/purchase-files/{file_id}/complete", { params: { path: { business_id: businessId, file_id: started.file_id } } }),
      );
      return started.file_id;
    },
    onSuccess: () => {
      key.current = crypto.randomUUID();
      queryClient.invalidateQueries({ queryKey: purchasesKey(businessId) });
    },
  });
}

export function useConfirmDraft(businessId: string, draftId: string) {
  const queryClient = useQueryClient();
  return useMutation<Confirmed, ApiError, ConfirmIn>({
    mutationFn: (body) =>
      call(() => api.POST("/api/v1/b/{business_id}/purchase-drafts/{draft_id}/confirm", { params: { path: { business_id: businessId, draft_id: draftId } }, body })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: purchasesKey(businessId) }),
  });
}

export function useDiscardDraft(businessId: string, draftId: string) {
  const queryClient = useQueryClient();
  return useMutation<unknown, ApiError, void>({
    mutationFn: () => call(() => api.POST("/api/v1/b/{business_id}/purchase-drafts/{draft_id}/discard", { params: { path: { business_id: businessId, draft_id: draftId } } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: purchasesKey(businessId) }),
  });
}

export async function codeAvailable(businessId: string, code: string): Promise<boolean> {
  const out = await call(() => api.GET("/api/v1/b/{business_id}/purchase-code-check", { params: { path: { business_id: businessId }, query: { code } } }));
  return out.available;
}

/** The business's active products (up to a page), for putting a line into one that exists. */
export function useActiveProducts(businessId: string) {
  return useQuery({
    queryKey: ["b", businessId, "products", "for-purchases"],
    queryFn: async () =>
      (await call(() => api.GET("/api/v1/b/{business_id}/products", { params: { path: { business_id: businessId }, query: { status: "active", limit: 100, offset: 0 } } }))).items,
    enabled: Boolean(businessId),
  });
}
