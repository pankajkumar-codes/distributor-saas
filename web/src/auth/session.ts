import { API_CREDENTIALS, API_ORIGIN } from "../api/origin";
import { withAuthTimeout } from "../api/timeout";
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

// True from the moment this tab's user pressed the Sign out button until the next sign-in, so
// the redirect is a plain /signin and does not remember the page they left. (Sign-in-again
// flows, like the stale sign-in on Security, sign out with the page remembered.)
let leftOnPurpose = false;
export const signedOutOnPurpose = () => leftOnPurpose;

// True when this tab held a session and the server then refused it (401 on a call and on the refresh): the
// session timed out or was ended elsewhere. The sign-in page says so. A visitor who never had a session in this
// tab (a fresh load with no cookie) is just signed out, and is told nothing.
let hadSession = false;
let timedOut = false;

/**
 * A plain cookie that says only "a session may exist here", no identity and no token. The refresh cookie is HttpOnly and
 * scoped to /api/v1/auth, so the web server cannot see it; this hint lets it show the landing page at "/" to visitors and
 * the app to people who are signed in. A stale hint costs one redirect to sign-in, which then clears it.
 */
function setSignedInHint(signedIn: boolean) {
  try {
    const secure = typeof location !== "undefined" && location.protocol === "https:" ? "; Secure" : "";
    document.cookie = signedIn ? `kartaa_in=1; Path=/; Max-Age=${30 * 24 * 3600}; SameSite=Lax${secure}` : `kartaa_in=; Path=/; Max-Age=0; SameSite=Lax${secure}`;
  } catch {
    // no document (a test without one) or cookies blocked: the landing page is then shown at "/", which is harmless
  }
}

function emit(signedIn: boolean, change: Change = "new") {
  setSignedInHint(signedIn);
  if (signedIn) leftOnPurpose = false;
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
  hadSession = true;
  timedOut = false;
  signOutUnconfirmed = false;
  signOutEnded = false;
  if (retryTimer) clearTimeout(retryTimer);
  retryTimer = null;
  noticeChanged();
  tokenStore.set(accessToken, expiresIn);
  bus()?.postMessage({ type: "token", accessToken, expiresIn, change } satisfies Message);
  emit(true, change);
}

/**
 * "ok": a fresh token is in memory. "signed_out": the server said 401, so the session is
 * gone and every listener hears it. "unavailable": offline, 429 or 5xx; the session may
 * still be fine, so nothing is cleared and the caller can try again.
 */
export type RefreshResult = "ok" | "signed_out" | "unavailable" | "slow";

// How long a refresh waits for another tab that holds the refresh lock before giving up (the refresh itself has its own 20 s).
const LOCK_WAIT_MS = 25_000;

async function refreshNow(background: boolean, rejected: string | null): Promise<RefreshResult> {
  if (signOutUnconfirmed) return "signed_out";
  // Another tab refreshed while this one waited for the lock: use its token, unless it is
  // the very token the server just refused.
  const held = tokenStore.get();
  if (Date.now() - receivedAt < RECENT_MS && held && held !== rejected) return "ok";
  let response: Response;
  try {
    response = await globalThis.fetch(API_ORIGIN + REFRESH, {
      method: "POST",
      credentials: API_CREDENTIALS,
      headers: background ? { "X-Background": "1" } : {},
      // 20 s limit: a refresh that never answers would leave the app on "Loading" with no way out. If the server did
      // rotate the cookie and the answer was lost, the next refresh is refused as a reuse and the person signs in
      // again, which is safe. A timeout reads as "unavailable": a plain message and a manual Try again, no retry loop.
      signal: withAuthTimeout(),
    });
  } catch (e) {
    // Gave up waiting (the server may only be slow) reads differently from no connection at all.
    return (e as Error | undefined)?.name === "TimeoutError" ? "slow" : "unavailable";
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
  // The wait for the cross-tab lock has a limit too: another tab stuck holding it must not leave this one on "checking".
  // A lock that is not granted in time reads as "unavailable", like a refresh that got no answer.
  const run = (): Promise<RefreshResult> => {
    if (typeof navigator === "undefined" || !navigator.locks) return refreshNow(background, rejected);
    const giveUp = new AbortController();
    const timer = setTimeout(() => giveUp.abort(), LOCK_WAIT_MS);
    return navigator.locks
      .request("auth-refresh", { signal: giveUp.signal }, () => {
        clearTimeout(timer); // the lock is ours: the refresh's own limit takes over
        return refreshNow(background, rejected);
      })
      .then((r) => r)
      .catch((): RefreshResult => "unavailable")
      .finally(() => clearTimeout(timer));
  };
  if (!inFlight) {
    inFlight = run().finally(() => {
      inFlight = null;
    });
  }
  return inFlight;
}

/** This tab's session is over (the server refused it): clear it and tell the listeners. */
export function endSession() {
  if (hadSession && !leftOnPurpose) timedOut = true;
  hadSession = false;
  tokenStore.clear();
  emit(false);
  noticeChanged();
}

// A sign-out that waits on a stalled server must still sign the user out of this tab, and quickly: the person
// is looking at a button that said "Sign out". The server finishes the job on its own if it is merely slow.
const SIGNOUT_TIMEOUT_MS = 2_000;

// True when the server's answer to a sign-out never arrived (too slow, offline, a 5xx). The browser may then still hold
// the old refresh cookie, so until the next sign-in this tab does not ask the server to refresh with it: the
// sign-in page would otherwise sign the person straight back in, or a slow sign-out would later end their new session.
let signOutUnconfirmed = false;
let signOutEnded = false; // the one background retry found the server session ended
let retried = false; // the one background retry has been made
let retryTimer: ReturnType<typeof setTimeout> | null = null;
const RETRY_AFTER_MS = 5_000;
const noticeListeners = new Set<() => void>();
const noticeChanged = () => noticeListeners.forEach((l) => l());

/** What the sign-in page says about the last sign-out: nothing, "we could not end it", or "it has now ended". */
export type SignOutNotice = "none" | "timed_out" | "not_ended" | "still_not_ended" | "ended_later";
export const signOutNotice = (): SignOutNotice =>
  timedOut ? "timed_out" : signOutUnconfirmed ? (retried ? "still_not_ended" : "not_ended") : signOutEnded ? "ended_later" : "none";
export function onSignOutNotice(listener: () => void): () => void {
  noticeListeners.add(listener);
  return () => noticeListeners.delete(listener);
}

/** One sign-out request, with the 2 s limit. True when the server answered in a way that means the session is over. */
async function askSignOut(token: string | null): Promise<boolean> {
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), SIGNOUT_TIMEOUT_MS);
  try {
    const response = await globalThis.fetch(API_ORIGIN + SIGNOUT, {
      method: "POST",
      credentials: API_CREDENTIALS,
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      signal: abort.signal,
    });
    // 204 is done. A refusal (401, 403) says there is no session to end. A 5xx or 429 is "not done".
    return response.status < 500 && response.status !== 429;
  } catch {
    return false; // offline or too slow: the server session stays until it expires
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Ends the session on the server, then in every tab. However the server answers (204, a
 * refusal such as 401 or 403, a 5xx, a network error, or no answer within 2 s) this tab is
 * signed out, and the call neither throws nor hangs: a Sign out button must never do nothing.
 * When the server did not confirm, the sign-in page says so, and the request is made once
 * more in the background a few seconds later (cookie only: this tab has no token any more).
 */
export async function signOut({ rememberPage = true }: { rememberPage?: boolean } = {}) {
  leftOnPurpose = !rememberPage;
  hadSession = false;
  timedOut = false;
  const token = tokenStore.get();
  const confirmed = await askSignOut(token);
  signOutEnded = false;
  retried = false;
  if (!confirmed) {
    signOutUnconfirmed = true;
    if (retryTimer) clearTimeout(retryTimer);
    retryTimer = setTimeout(async () => {
      retryTimer = null;
      if (!signOutUnconfirmed) return; // the person signed in again meanwhile: that session is theirs to keep
      retried = true;
      if (await askSignOut(null)) {
        signOutUnconfirmed = false;
        signOutEnded = true;
      }
      noticeChanged();
    }, RETRY_AFTER_MS);
  }
  tokenStore.clear();
  try {
    bus()?.postMessage({ type: "signed_out" } satisfies Message);
  } catch {
    // A closed channel only means no other tab hears it; they find out on their next refresh.
  }
  emit(false);
  noticeChanged();
}

/** For tests: forget the channel and timers between cases. */
export function resetSessionForTests() {
  channel?.close();
  channel = null;
  receivedAt = 0;
  inFlight = null;
  leftOnPurpose = false;
  hadSession = false;
  timedOut = false;
  signOutUnconfirmed = false;
  signOutEnded = false;
  if (retryTimer) clearTimeout(retryTimer);
  retryTimer = null;
  noticeListeners.clear();
  listeners.clear();
  tokenStore.clear();
}
