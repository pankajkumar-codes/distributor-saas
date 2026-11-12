import { useQuery } from "@tanstack/react-query";

import { api, call } from "../api/client";
import type { ApiError } from "../api/errors";
import type { components } from "../api/schema";

export type Me = components["schemas"]["MeOut"];

/** GET /me: who is signed in, and whether two-step sign-in is on (LLD-1 §5.9). */
export function useMe({ enabled = true }: { enabled?: boolean } = {}) {
  return useQuery<Me, ApiError>({ queryKey: ["me"], queryFn: () => call(() => api.GET("/api/v1/me")), enabled });
}

// H-1 item 3: two-step sign-in is offered to everyone, off by default (TD-4a), and the
// app asks owners and CAs to turn it on.
export const TOTP_PROMPTED = new Set(["owner", "ca"]);
