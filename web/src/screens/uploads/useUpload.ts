import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef } from "react";

import { api, call } from "../../api/client";
import type { ApiError } from "../../api/errors";
import { uploadTo } from "../../api/upload";
import { pollDelay } from "../../api/useJob";
import { settled, type Section, type Upload } from "./sections";

export const uploadsKey = (businessId: string) => ["b", businessId, "uploads"];

/** Follows one upload until the server has settled it (parsed, rejected, stored or expired). */
export function useUpload(businessId: string, uploadId: string | null) {
  return useQuery<Upload, ApiError>({
    queryKey: [...uploadsKey(businessId), uploadId],
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/uploads/{upload_id}", { params: { path: { business_id: businessId, upload_id: uploadId ?? "" } } })),
    enabled: Boolean(businessId && uploadId),
    refetchIntervalInBackground: true, // a hidden tab still finds out the file was read
    // dataUpdateCount is already 1 after the first answer, so the gap after answer n is pollDelay(n - 1).
    refetchInterval: (query) => (settled(query.state.data) || query.state.error ? false : pollDelay(Math.max(0, query.state.dataUpdateCount - 1))),
  });
}

/** The recent uploads of one section, newest first. */
export function useUploads(businessId: string, section: Section | null, enabled = true) {
  return useQuery<Upload[], ApiError>({
    queryKey: [...uploadsKey(businessId), "list", section],
    queryFn: async () =>
      (await call(() => api.GET("/api/v1/b/{business_id}/uploads", { params: { path: { business_id: businessId }, query: { section: section ?? undefined } } }))).uploads,
    enabled: enabled && Boolean(businessId),
  });
}

/**
 * Start, send, complete: the browser posts the file to the storage link the server gave
 * (never through the API), then tells the server it arrived. One Idempotency-Key per chosen
 * file, so a retry of the same choice never makes a second upload; a failed send rotates it,
 * because the link may have expired.
 */
export function useStartUpload(businessId: string, onStarted: (uploadId: string) => void) {
  const queryClient = useQueryClient();
  const key = useRef(crypto.randomUUID());
  const mutation = useMutation<string, ApiError, { section: Section; file: File }>({
    mutationFn: async ({ section, file }) => {
      const started = await call(() =>
        api.POST("/api/v1/b/{business_id}/uploads", {
          params: { path: { business_id: businessId }, header: { "Idempotency-Key": key.current } },
          body: { section, file_name: file.name, size_bytes: file.size },
        }),
      );
      try {
        await uploadTo(started.upload, file);
      } catch (e) {
        key.current = crypto.randomUUID();
        throw e;
      }
      await call(() => api.POST("/api/v1/b/{business_id}/uploads/{upload_id}/complete", { params: { path: { business_id: businessId, upload_id: started.upload_id } } }));
      return started.upload_id;
    },
    onSuccess: (uploadId) => {
      key.current = crypto.randomUUID();
      queryClient.invalidateQueries({ queryKey: uploadsKey(businessId) });
      onStarted(uploadId);
    },
  });
  return { ...mutation, newChoice: () => (key.current = crypto.randomUUID()) };
}
