import createClient from "openapi-fetch";

import { refreshSession } from "../auth/session";
import { tokenStore } from "../auth/tokenStore";
import { toApiError, type ApiError } from "./errors";
import type { paths } from "./schema";

// Typed from app/openapi.json (`npm run gen:api`). Same origin only: the API is served
// under /api on the app's own domain, so the refresh cookie never crosses sites.
export const api = createClient<paths>({
  baseUrl: window.location.origin,
  // Looked up per call, so tests can stub the global fetch.
  fetch: (request) => globalThis.fetch(request),
});

api.use({
  onRequest({ request }) {
    const token = tokenStore.get();
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
});

type Result<T> = { data?: T; error?: unknown; response: Response };

async function once<T>(request: () => Promise<Result<T>>): Promise<T> {
  let result;
  try {
    result = await request();
  } catch {
    throw toApiError(undefined, undefined);
  }
  if (!result.response.ok) throw toApiError(result.response, result.error);
  return result.data as T;
}

/**
 * Resolves to the body of a 2xx, or rejects with an ApiError (status 0 if unreachable).
 * A 401 session_invalid gets one refresh and one retry (LLD-1 §11.3); if that fails too,
 * the session listeners hear about it and the app goes to sign-in. The /auth calls pass
 * `refresh: false`: a retried code check would spend one of the user's tries.
 */
export async function call<T>(request: () => Promise<Result<T>>, { refresh = true } = {}): Promise<T> {
  try {
    return await once(request);
  } catch (e) {
    const error = e as ApiError;
    if (!refresh || error.status !== 401 || error.code !== "session_invalid") throw error;
    if (!(await refreshSession())) throw error;
    return once(request);
  }
}
