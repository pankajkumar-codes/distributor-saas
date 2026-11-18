import { render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { fakeApi } from "./fakeApi";

const REFRESH = "/api/v1/auth/refresh";
const ME = "/api/v1/me/businesses";

let server: ReturnType<typeof fakeApi>;
beforeEach(() => {
  resetSessionForTests();
  server = fakeApi();
});
afterEach(() => vi.unstubAllGlobals());

const open = () => {
  window.history.replaceState(null, "", "/");
  render(<App />);
};

describe("/ inside the app (the web server shows the landing page to visitors; the app gets signed-in people)", () => {
  it("sends someone with no session to sign-in", async () => {
    server.reply(REFRESH, { status: 401, body: { error: { code: "session_invalid" } } });
    open();
    await waitFor(() => expect(window.location.pathname).toBe("/signin"));
  });

  it("sends a signed-in person to their home, or to onboarding when they have no business yet", async () => {
    server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
    server.reply(ME, { status: 200, body: { is_support: false, businesses: [{ business_id: "b-1", display_name: "Vashi Essentials", gstin: null, role: "owner" }] } });
    open();
    await waitFor(() => expect(window.location.pathname).toBe("/b/b-1/home"));
  });

  it("sends support staff to their own list", async () => {
    server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
    server.reply(ME, { status: 200, body: { is_support: true, businesses: [] } });
    open();
    await waitFor(() => expect(window.location.pathname).toBe("/support"));
  });
});

describe("the signed-in hint cookie", () => {
  it("is set while a session exists and cleared when it ends", async () => {
    server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
    server.reply(ME, { status: 200, body: { is_support: false, businesses: [] } });
    open();
    await waitFor(() => expect(document.cookie).toContain("kartaa_in=1"));
    const { endSession } = await import("../../src/auth/session");
    endSession();
    expect(document.cookie).not.toContain("kartaa_in=1");
  });
});
