// The sign-in, sign-up and refresh calls are short. If one gets no answer in this time it is given up, so the
// screen shows "we couldn't reach the server" and its button works again instead of staying greyed out. Uploads
// and downloads are not under /auth and are left alone.
export const AUTH_TIMEOUT_MS = 20_000;

/** The time limit joined with the caller's own abort signal, if it has one: either one ends the request. */
export function withAuthTimeout(own?: AbortSignal): AbortSignal {
  const limit = AbortSignal.timeout(AUTH_TIMEOUT_MS);
  return own ? AbortSignal.any([own, limit]) : limit;
}

export const isAuthPath = (url: string) => new URL(url).pathname.startsWith("/api/v1/auth/");
