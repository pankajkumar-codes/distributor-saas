import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, call } from "../../src/api/client";
import { onSessionChange, refreshSession, resetSessionForTests, signOut, startSession } from "../../src/auth/session";
import { tokenStore } from "../../src/auth/tokenStore";
import { fakeApi } from "./fakeApi";

const REFRESH = "/api/v1/auth/refresh";
const fresh = (token: string) => ({ status: 200, body: { access_token: token, expires_in: 3600 } });
const tick = () => new Promise((r) => setTimeout(r, 20));

let server: ReturnType<typeof fakeApi>;
let otherTab: BroadcastChannel;
let heard: unknown[];

beforeEach(() => {
  resetSessionForTests();
  server = fakeApi();
  heard = [];
  otherTab = new BroadcastChannel("auth");
  otherTab.onmessage = (e) => heard.push(e.data);
});

afterEach(() => {
  otherTab.close();
  vi.unstubAllGlobals();
});

describe("refreshSession", () => {
  it("keeps the new token in memory and hands it to the other tabs", async () => {
    server.reply(REFRESH, fresh("t1"));
    expect(await refreshSession()).toBe(true);
    expect(tokenStore.get()).toBe("t1");
    await tick();
    expect(heard).toEqual([{ type: "token", accessToken: "t1", expiresIn: 3600 }]);
  });

  it("sends one refresh for calls that overlap", async () => {
    server.reply(REFRESH, fresh("t1"));
    const both = await Promise.all([refreshSession(), refreshSession()]);
    expect(both).toEqual([true, true]);
    expect(server.paths()).toEqual([REFRESH]);
  });

  it("runs under the 'auth-refresh' Web Lock when the browser has one", async () => {
    const request = vi.fn((_name: string, run: () => Promise<boolean>) => run());
    vi.stubGlobal("navigator", { locks: { request } });
    server.reply(REFRESH, fresh("t1"));
    await refreshSession();
    expect(request).toHaveBeenCalledWith("auth-refresh", expect.any(Function));
  });

  it("uses a token another tab sent in the last 30 seconds instead of calling", async () => {
    onSessionChange(() => {}); // opens this tab's channel
    otherTab.postMessage({ type: "token", accessToken: "from-tab-2", expiresIn: 3600 });
    await tick();
    expect(await refreshSession()).toBe(true);
    expect(tokenStore.get()).toBe("from-tab-2");
    expect(server.paths()).toEqual([]);
  });

  it("signs out on a 401, and marks background polls", async () => {
    const seen: boolean[] = [];
    onSessionChange((signedIn) => seen.push(signedIn));
    tokenStore.set("old", 1);
    expect(await refreshSession({ background: true })).toBe(false);
    expect(tokenStore.get()).toBeNull();
    expect(seen).toEqual([false]);
    expect(server.sent[0].headers.get("X-Background")).toBe("1");
  });
});

describe("signOut", () => {
  it("revokes on the server, clears the token, and tells every tab", async () => {
    startSession("t1", 3600);
    server.reply("/api/v1/auth/signout", { status: 204 });
    await signOut();
    const out = server.sent.find((s) => s.path === "/api/v1/auth/signout")!;
    expect(out.headers.get("Authorization")).toBe("Bearer t1");
    expect(tokenStore.get()).toBeNull();
    await tick();
    expect(heard).toContainEqual({ type: "signed_out" });
  });

  it("follows a sign-out from another tab", async () => {
    const seen: boolean[] = [];
    onSessionChange((signedIn) => seen.push(signedIn));
    tokenStore.set("t1", 3600);
    otherTab.postMessage({ type: "signed_out" });
    await tick();
    expect(tokenStore.get()).toBeNull();
    expect(seen).toEqual([false]);
  });
});

describe("call", () => {
  const ME = "/api/v1/me/businesses";
  const expired = { status: 401, body: { error: { code: "session_invalid", message: "sign in again" } } };

  it("refreshes once on session_invalid and retries with the new token", async () => {
    tokenStore.set("stale", 3600);
    server.reply(ME, expired, { status: 200, body: { businesses: [] } });
    server.reply(REFRESH, fresh("t2"));
    expect(await call(() => api.GET(ME))).toEqual({ businesses: [] });
    expect(server.paths()).toEqual([ME, REFRESH, ME]);
    expect(server.sent[2].headers.get("Authorization")).toBe("Bearer t2");
  });

  it("gives up when the refresh fails too", async () => {
    server.reply(ME, expired);
    await expect(call(() => api.GET(ME))).rejects.toMatchObject({ status: 401, code: "session_invalid" });
    expect(server.paths()).toEqual([ME, REFRESH]);
  });

  it("never retries an /auth call, which could spend a code try", async () => {
    server.reply("/api/v1/auth/signin", expired);
    await expect(
      call(() => api.POST("/api/v1/auth/signin", { body: { email: "a@b.in", password: "x" } }), { refresh: false }),
    ).rejects.toMatchObject({ status: 401 });
    expect(server.paths()).toEqual(["/api/v1/auth/signin"]);
  });
});
