import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { pollDelay } from "../../api/useJob";
import { api, call } from "../../api/client";
import type { ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { uploadTo } from "../../api/upload";
import { uploadsKey } from "./useUpload";

export type Bundle = components["schemas"]["BundleOut"];
export type BundleFile = components["schemas"]["BundleFileOut"];
type Section = components["schemas"]["BundleChoiceIn"]["section"];

const bundleKey = (businessId: string, bundleId: string | null) => ["b", businessId, "bundle", bundleId];
// The server is still working on the zip in these states; the user waits.
const BUSY = new Set<Bundle["status"]>(["pending", "received", "staging"]);
const GIVE_UP_MS = 15 * 60 * 1000;

/** True when a bundle is still being worked on but the page has stopped looking (it is older than 15 minutes). */
export function pollingGaveUp(b: Pick<Bundle, "status" | "created_at">, staging: boolean): boolean {
  const busy = BUSY.has(b.status) || (staging && b.status === "classified");
  return busy && Date.now() - Date.parse(b.created_at) > GIVE_UP_MS;
}

/** A file name for the screen: the invisible text-direction controls that can make a name read as another name are removed. */
export function shownName(name: string): string {
  return name.replace(/[\u200E\u200F\u202A-\u202E\u2066-\u2069]/g, "");
}

/**
 * Follows one bundle. It looks again every few seconds while the server sorts or stages it, and stops once
 * it is ready for the user (classified), staged, rejected or expired. `staging` is true right after the user
 * pressed the button, when the server may not have started the job yet and still says "classified".
 */
export function useBundle(businessId: string, bundleId: string | null, staging = false) {
  return useQuery<Bundle, ApiError>({
    queryKey: bundleKey(businessId, bundleId),
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/upload-bundles/{bundle_id}", { params: { path: { business_id: businessId, bundle_id: bundleId ?? "" } } })),
    enabled: Boolean(businessId && bundleId),
    refetchIntervalInBackground: false,
    refetchInterval: (q) => {
      const b = q.state.data;
      if (q.state.error || !b || Date.now() - Date.parse(b.created_at) > GIVE_UP_MS) return false;
      return BUSY.has(b.status) || (staging && b.status === "classified") ? pollDelay(Math.max(0, q.state.dataUpdateCount - 1)) : false;
    },
  });
}

/** Start, send the zip to the storage link, complete. A failed send takes a new key, because the link may have expired. */
export async function sendBundle(businessId: string, file: File, key: { current: string }): Promise<string> {
  const started = await call(() =>
    api.POST("/api/v1/b/{business_id}/upload-bundles", {
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
  await call(() => api.POST("/api/v1/b/{business_id}/upload-bundles/{bundle_id}/complete", { params: { path: { business_id: businessId, bundle_id: started.bundle_id } } }));
  return started.bundle_id;
}

/** Move one file to a section the business has, or drop it (null). The server may refuse, in words. */
export function useChooseFile(businessId: string, bundleId: string) {
  const queryClient = useQueryClient();
  return useMutation<Bundle, ApiError, { n: number; section: Section }>({
    mutationFn: ({ n, section }) =>
      call(() =>
        api.PATCH("/api/v1/b/{business_id}/upload-bundles/{bundle_id}/files/{n}", {
          params: { path: { business_id: businessId, bundle_id: bundleId, n } },
          body: { section },
        }),
      ),
    onSuccess: (bundle) => queryClient.setQueryData(bundleKey(businessId, bundleId), bundle),
  });
}

/** Stage the files that will be read: one ordinary upload per file, made by a job. */
export function useStageBundle(businessId: string, bundleId: string) {
  const queryClient = useQueryClient();
  return useMutation<unknown, ApiError, void>({
    mutationFn: () => call(() => api.POST("/api/v1/b/{business_id}/upload-bundles/{bundle_id}/stage", { params: { path: { business_id: businessId, bundle_id: bundleId } } })),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: bundleKey(businessId, bundleId) });
      void queryClient.invalidateQueries({ queryKey: uploadsKey(businessId) });
    },
  });
}
