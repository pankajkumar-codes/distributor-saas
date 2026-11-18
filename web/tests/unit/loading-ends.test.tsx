import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { fakeApi } from "./fakeApi";

const REFRESH = "/api/v1/auth/refresh";
const ME = "/api/v1/me/businesses";
const me = { status: 200, body: { businesses: [{ business_id: "b-1", display_name: "Vashi Essentials", gstin: null, role: "owner" }] } };

// Every list page has to end in records, an empty message, or an error with Try again, never in "Loading…" for ever.
// A request that gets no answer is cut off by the read time limit (shortened here) and the page says so.
describe("a list page whose request gets no answer", () => {
  beforeEach(() => {
    resetSessionForTests();
    window.history.replaceState(null, "", "/");
  });
  afterEach(() => vi.unstubAllGlobals());

  function hang(path: string) {
    const real = AbortSignal.timeout.bind(AbortSignal);
    const spy = vi.spyOn(AbortSignal, "timeout").mockImplementation(() => real(30));
    onTestFinished(() => spy.mockRestore());
    const server = fakeApi();
    server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
    server.reply(ME, me);
    const inner = globalThis.fetch as typeof fetch;
    let calls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: Request | string, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.url;
        if (new URL(url, "http://localhost").pathname !== path) return inner(input, init);
        calls += 1;
        return new Promise<Response>((_, reject) => init?.signal?.addEventListener("abort", () => reject(init.signal?.reason)));
      }),
    );
    return () => calls;
  }

  it.each([
    ["Products", "/b/b-1/products", "/api/v1/b/b-1/products"],
    ["Customers", "/b/b-1/customers", "/api/v1/b/b-1/customers"],
    ["Audit log", "/b/b-1/settings/audit", "/api/v1/b/b-1/audit-log"],
    ["Support access", "/b/b-1/settings/support", "/api/v1/b/b-1/support-grants"],
  ])("%s ends in an error with Try again, asked once, and Try again asks again", async (_name, route, api) => {
    const calls = hang(api);
    window.history.replaceState(null, "", route);
    render(<App />);
    expect(await screen.findByText(/The server is taking too long to answer/)).toBeInTheDocument();
    expect(screen.queryByText("Loading…")).not.toBeInTheDocument();
    expect(screen.getByText(`Details: GET ${api}: no answer in time.`)).toBeInTheDocument(); // which request, for support
    expect(calls()).toBe(1);
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await vi.waitFor(() => expect(calls()).toBe(2));
  });
});
