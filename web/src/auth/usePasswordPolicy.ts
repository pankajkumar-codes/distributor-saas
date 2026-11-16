import { useQuery } from "@tanstack/react-query";

import { api, call } from "../api/client";
import type { ApiError } from "../api/errors";
import type { components } from "../api/schema";

import { useAuthStatus } from "./AuthProvider";

export type PasswordPolicy = components["schemas"]["PasswordPolicyOut"];

/**
 * GET /auth/password-policy: the rules in force, from the server, so no screen keeps its own copy.
 * Waits for the first session check, because a signed-out answer clears the query cache.
 */
export function usePasswordPolicy() {
  const status = useAuthStatus();
  return useQuery<PasswordPolicy, ApiError>({
    queryKey: ["password-policy"],
    queryFn: () => call(() => api.GET("/api/v1/auth/password-policy"), { refresh: false }),
    staleTime: 10 * 60_000,
    enabled: status !== "checking",
  });
}
