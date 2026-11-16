// The sign-in, sign-up and refresh calls are short. If one gets no answer in this time it is given up, so the
// screen shows "we couldn't reach the server" and its button works again instead of staying greyed out. Uploads
// and downloads are not under /auth and are left alone.
// A request given up here may still have reached the server (slow, not lost). Pressing the button again then sends
// a second sign-up code and the first stops working: one extra email, never a second account, because the account
// is only made when a code is verified.
export const AUTH_TIMEOUT_MS = 20_000;
// A list or detail page that gets no answer in this time shows "We couldn't reach the server" with Try again,
// instead of "Loading…" for ever. Only reads (GET) are limited: a write that is given up may still have happened.
// This covers every GET, so a large download (exports, the CA pack in M8) must use its own limit or opt out.
export const READ_TIMEOUT_MS = 30_000;

/** The time limit joined with the caller's own abort signal, if it has one: either one ends the request. */
export function withAuthTimeout(own?: AbortSignal, ms = AUTH_TIMEOUT_MS): AbortSignal {
  const limit = AbortSignal.timeout(ms);
  if (!own) return limit;
  if (typeof AbortSignal.any === "function") return AbortSignal.any([own, limit]); // Chrome 116, Firefox 124, Safari 17.4
  // Older browsers: one controller that either signal ends.
  const joined = new AbortController();
  for (const signal of [own, limit]) {
    if (signal.aborted) joined.abort(signal.reason);
    else signal.addEventListener("abort", () => joined.abort(signal.reason), { once: true });
  }
  return joined.signal;
}

export const isAuthPath = (url: string) => new URL(url).pathname.startsWith("/api/v1/auth/");
