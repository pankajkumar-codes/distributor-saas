import { tokenStore } from "./tokenStore";

// LLD-1 §11.3. The refresh cookie is HttpOnly, so the page never sees it: a reload asks
// /auth/refresh for a new access token. Tabs share one refresh under a Web Lock, and the
// tab holding it posts the token on BroadcastChannel('auth'), so the others don't call
// again. Sign-out is posted the same way and every tab signs out.

const REFRESH = "/api/v1/auth/refresh";
const SIGNOUT = "/api/v1/auth/signout";
const RECENT_MS = 30_000;

// "refresh" is the same session with a new token; "new" may be a different user (a sign-in
// or sign-up here or in another tab), so anything cached for the old one must go.
export type Change = "refresh" | "new";
type Message = { type: "token"; accessToken: string; expiresIn: number; change: Change } | { type: "signed_out" };
type Listener = (signedIn: boolean, change: Change) => void;

const listeners = new Set<Listener>();
let channel: BroadcastChannel | null = null;
let receivedAt = 0;
let inFlight: Promise<RefreshResult> | null = null;

function emit(signedIn: boolean, change: Change = "new") {
  listeners.forEach((listener) => listener(signedIn, change));
}

// The access token crosses BroadcastChannel('auth'). That reaches only same-origin pages,
// and any same-origin script could already read the token from this module's memory, so
// the channel exposes nothing new (Lead, #46). The refresh cookie never crosses it.
function bus(): BroadcastChannel | null {
  if (!channel && typeof BroadcastChannel !== "undefined") {
    channel = new BroadcastChannel("auth");
    channel.onmessage = (e: MessageEvent<Message>) => {
      if (e.data.type === "token") {
        tokenStore.set(e.data.accessToken, e.data.expiresIn);
        receivedAt = Date.now();
        emit(true, e.data.change);
      } else if (e.data.type === "signed_out") {
        tokenStore.clear();
        emit(false);
      }
    };
  }
  return channel;
}

/** Called with true when this tab gains or renews a session and false when it loses one. */
export function onSessionChange(listener: Listener): () => void {
  bus();
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Keep a token from sign-up, sign-in or a refresh, and hand it to the other tabs. */
export function startSession(accessToken: string, expiresIn: number, change: Change = "new") {
  tokenStore.set(accessToken, expiresIn);
  bus()?.postMessage({ type: "token", accessToken, expiresIn, change } satisfies Message);
  emit(true, change);
}

/**
 * "ok": a fresh token is in memory. "signed_out": the server said 401, so the session is
 * gone and every listener hears it. "unavailable": offline, 429 or 5xx; the session may
 * still be fine, so nothing is cleared and the caller can try again.
 */
export type RefreshResult = "ok" | "signed_out" | "unavailable";

async function refreshNow(background: boolean, rejected: string | null): Promise<RefreshResult> {
  // Another tab refreshed while this one waited for the lock: use its token, unless it is
  // the very token the server just refused.
  const held = tokenStore.get();
  if (Date.now() - receivedAt < RECENT_MS && held && held !== rejected) return "ok";
  let response: Response;
  try {
    response = await globalThis.fetch(window.location.origin + REFRESH, {
      method: "POST",
      credentials: "same-origin",
      headers: background ? { "X-Background": "1" } : {},
    });
  } catch {
    return "unavailable";
  }
  if (response.status === 401) {
    endSession();
    return "signed_out";
  }
  if (!response.ok) return "unavailable";
  const body = (await response.json()) as { access_token: string; expires_in: number };
  startSession(body.access_token, body.expires_in, "refresh");
  return "ok";
}

/**
 * One refresh at a time per tab, and one across tabs where Web Locks exist. `rejected` is
 * the token a 401 just came back for, so a token shared by another tab isn't trusted
 * again once the server has refused it.
 */
export function refreshSession({
  background = false,
  rejected = null,
}: { background?: boolean; rejected?: string | null } = {}): Promise<RefreshResult> {
  const run = (): Promise<RefreshResult> =>
    typeof navigator !== "undefined" && navigator.locks
      ? navigator.locks.request("auth-refresh", () => refreshNow(background, rejected)).then((r) => r)
      : refreshNow(background, rejected);
  if (!inFlight) {
    inFlight = run().finally(() => {
      inFlight = null;
    });
  }
  return inFlight;
}

/** This tab's session is over (the server refused it): clear it and tell the listeners. */
export function endSession() {
  tokenStore.clear();
  emit(false);
}

/** Ends the session on the server, then in every tab. Never fails from the user's side. */
export async function signOut() {
  const token = tokenStore.get();
  try {
    await globalThis.fetch(window.location.origin + SIGNOUT, {
      method: "POST",
      credentials: "same-origin",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
  } catch {
    // Offline: the server session stays until it expires, but this tab still signs out.
  }
  tokenStore.clear();
  bus()?.postMessage({ type: "signed_out" } satisfies Message);
  emit(false);
}

/** For tests: forget the channel and timers between cases. */
export function resetSessionForTests() {
  channel?.close();
  channel = null;
  receivedAt = 0;
  inFlight = null;
  listeners.clear();
  tokenStore.clear();
}
