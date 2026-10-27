import createClient from "openapi-fetch";

import { tokenStore } from "../auth/tokenStore";
import { toApiError } from "./errors";
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

/** Resolves to the body of a 2xx, or rejects with an ApiError (status 0 if unreachable). */
export async function call<T>(request: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  let result;
  try {
    result = await request;
  } catch {
    throw toApiError(undefined, undefined);
  }
  if (!result.response.ok) throw toApiError(result.response, result.error);
  return result.data as T;
}
