import { tokenStore } from "./tokenStore";

// LLD-1 §11.3. The refresh cookie is HttpOnly, so the page never sees it: a reload asks
// /auth/refresh for a new access token. Tabs share one refresh under a Web Lock, and the
// tab holding it posts the token on BroadcastChannel('auth'), so the others don't call
// again. Sign-out is posted the same way and every tab signs out.

const REFRESH = "/api/v1/auth/refresh";
const SIGNOUT = "/api/v1/auth/signout";
const RECENT_MS = 30_000;

type Message = { type: "token"; accessToken: string; expiresIn: number } | { type: "signed_out" };
type Listener = (signedIn: boolean) => void;

const listeners = new Set<Listener>();
let channel: BroadcastChannel | null = null;
let receivedAt = 0;
let inFlight: Promise<boolean> | null = null;

function emit(signedIn: boolean) {
  listeners.forEach((listener) => listener(signedIn));
}

function bus(): BroadcastChannel | null {
  if (!channel && typeof BroadcastChannel !== "undefined") {
    channel = new BroadcastChannel("auth");
    channel.onmessage = (e: MessageEvent<Message>) => {
      if (e.data.type === "token") {
        tokenStore.set(e.data.accessToken, e.data.expiresIn);
        receivedAt = Date.now();
        emit(true);
      } else if (e.data.type === "signed_out") {
        tokenStore.clear();
        emit(false);
      }
    };
  }
  return channel;
}

/** Called with true when this tab gains a session and false when it loses one. */
export function onSessionChange(listener: Listener): () => void {
  bus();
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Keep a token from sign-up or sign-in, and hand it to the other tabs. */
export function startSession(accessToken: string, expiresIn: number) {
  tokenStore.set(accessToken, expiresIn);
  bus()?.postMessage({ type: "token", accessToken, expiresIn } satisfies Message);
  emit(true);
}

async function refreshNow(background: boolean): Promise<boolean> {
  // Another tab refreshed while this one waited for the lock: use its token.
  if (Date.now() - receivedAt < RECENT_MS && tokenStore.get()) return true;
  let response: Response;
  try {
    response = await globalThis.fetch(window.location.origin + REFRESH, {
      method: "POST",
      credentials: "same-origin",
      headers: background ? { "X-Background": "1" } : {},
    });
  } catch {
    return false; // offline: keep whatever state we had; the next call tries again
  }
  if (!response.ok) {
    tokenStore.clear();
    emit(false);
    return false;
  }
  const body = (await response.json()) as { access_token: string; expires_in: number };
  startSession(body.access_token, body.expires_in);
  return true;
}

/** One refresh at a time per tab, and one across tabs where Web Locks exist. */
export function refreshSession({ background = false } = {}): Promise<boolean> {
  const run = (): Promise<boolean> =>
    typeof navigator !== "undefined" && navigator.locks
      ? navigator.locks.request("auth-refresh", () => refreshNow(background)).then((ok) => ok)
      : refreshNow(background);
  if (!inFlight) {
    inFlight = run().finally(() => {
      inFlight = null;
    });
  }
  return inFlight;
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
