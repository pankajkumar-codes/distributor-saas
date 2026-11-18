import createClient from "openapi-fetch";

import { endSession, refreshSession } from "../auth/session";
import { tokenStore } from "../auth/tokenStore";
import { toApiError, type ApiError } from "./errors";
import { isAuthPath, READ_TIMEOUT_MS, withAuthTimeout } from "./timeout";
import type { paths } from "./schema";

// Typed from app/openapi.json (`npm run gen:api`). Same origin only: the API is served
// under /api on the app's own domain, so the refresh cookie never crosses sites.
export const api = createClient<paths>({
  baseUrl: window.location.origin,
  // Looked up per call, so tests can stub the global fetch.
  fetch: async (request) => {
    try {
      return await globalThis.fetch(request, signalFor(request));
    } catch (e) {
      // Say which request, and whether it timed out, so a "couldn't reach the server" can be traced.
      const how = (e as Error | undefined)?.name === "TimeoutError" ? "no answer in time" : "no connection";
      throw Object.assign(e instanceof Error ? e : new Error(String(e)), { detail: `${request.method} ${new URL(request.url).pathname}: ${how}` });
    }
  },
});

function signalFor(request: Request): RequestInit | undefined {
  if (isAuthPath(request.url)) return { signal: withAuthTimeout(request.signal) };
  return request.method === "GET" ? { signal: withAuthTimeout(request.signal, READ_TIMEOUT_MS) } : undefined;
}

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
  } catch (e) {
    const error = toApiError(undefined, undefined, (e as { detail?: string } | undefined)?.detail);
    throw (e as Error | undefined)?.name === "TimeoutError" ? { ...error, code: "timeout" } : error;
  }
  if (!result.response.ok) {
    const { response } = result;
    throw toApiError(response, result.error, `${new URL(response.url || window.location.href).pathname}: answered ${response.status}`);
  }
  return result.data as T;
}

/**
 * Resolves to the body of a 2xx, or rejects with an ApiError (status 0 if unreachable).
 * A 401 session_invalid gets one refresh and one retry (LLD-1 §11.3); if that fails too,
 * or the retry is refused too, the session listeners hear it and the app goes to sign-in. The /auth calls pass
 * `refresh: false`: a retried code check would spend one of the user's tries.
 */
export async function call<T>(request: () => Promise<Result<T>>, { refresh = true } = {}): Promise<T> {
  const used = tokenStore.get();
  try {
    return await once(request);
  } catch (e) {
    if (!refresh || !sessionInvalid(e)) throw e;
    if ((await refreshSession({ rejected: used })) !== "ok") throw e;
  }
  try {
    return await once(request);
  } catch (e) {
    // Refused again with a fresh token: the session itself is gone, so sign the tab out.
    if (sessionInvalid(e)) endSession();
    throw e;
  }
}

function sessionInvalid(e: unknown): boolean {
  // Any 401 from a call that sends the session: the access token is gone or refused, whatever code a proxy or the
  // server put on it. A refresh then settles whether the session itself is over.
  return (e as ApiError).status === 401;
}
