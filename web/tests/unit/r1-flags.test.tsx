import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { fakeApi } from "./fakeApi";

const REFRESH = "/api/v1/auth/refresh";
const ME = "/api/v1/me/businesses";
const me = { status: 200, body: { businesses: [{ business_id: "b-1", display_name: "Vashi Essentials", gstin: null, role: "owner" }] } };
const home = { status: 200, body: { greeting_name: "Asha", checklist: { done: 0, total: 0, items: [] }, filing: null, hub: null, insights: null, attention: [] } };

let server: ReturnType<typeof fakeApi>;
beforeEach(() => {
  resetSessionForTests();
  server = fakeApi();
  server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
  server.reply(ME, me);
});
afterEach(() => vi.unstubAllGlobals());

const open = (path: string) => {
  window.history.replaceState(null, "", path);
  render(<App />);
};

describe("Release 1 has no invoicing", () => {
  it("Home has no Sell card, and the invoice screens are the not-found page", async () => {
    server.reply("/api/v1/b/b-1/home", home);
    open("/b/b-1/home");
    expect(await screen.findByRole("heading", { level: 1, name: /Asha/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "New invoice" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Sell" })).toBeNull();
  });

  it("the invoice editor route is not there", async () => {
    open("/b/b-1/invoices/new");
    expect(await screen.findByRole("heading", { name: "We couldn't find that page" })).toBeInTheDocument();
  });
});
