import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { msUntilFirst } from "../../src/screens/settings/SupportPage";
import { fakeApi } from "./fakeApi";

// Support staff's side of the web (LLD-2 §6.2): their list of businesses and the banner.
const REFRESH = "/api/v1/auth/refresh";
const ME = "/api/v1/me/businesses";
const GRANTS = "/api/v1/support/grants";
const HOME = "/api/v1/b/b-1/home";
const grant = { grant_id: "g-1", business_id: "b-1", business_name: "Vashi Essentials", expires_at: "2099-10-25T08:50:00Z" };
const support = { status: 200, body: { businesses: [], is_support: true } };
const home = {
  status: 200,
  body: { greeting_name: null, checklist: { done: 0, total: 0, items: [] }, filing: null, hub: null, insights: null, attention: [] },
};

let server: ReturnType<typeof fakeApi>;
beforeEach(() => {
  resetSessionForTests();
  server = fakeApi();
  server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
});
afterEach(() => vi.unstubAllGlobals());

function open(path: string) {
  window.history.replaceState(null, "", path);
  render(<App />);
}

describe("support staff", () => {
  it("lists the businesses they may open, with when access ends", async () => {
    server.reply(GRANTS, { status: 200, body: { grants: [grant] } });
    open("/support");
    const item = (await screen.findByRole("link", { name: "Vashi Essentials" })).closest("li") as HTMLElement;
    expect(within(item).getByRole("link")).toHaveAttribute("href", "/b/b-1/home");
    expect(item).toHaveTextContent("access ends 25-Oct-2099, 14:20");
  });

  it("says so when no business has given access", async () => {
    server.reply(GRANTS, { status: 200, body: { grants: [] } });
    open("/support");
    expect(await screen.findByText("No business has given support access right now.")).toBeInTheDocument();
  });

  it("is not found for anyone who isn't support (the server's 404)", async () => {
    server.reply(GRANTS, { status: 404, body: { error: { code: "not_found", message: "not found" } } });
    open("/support");
    expect(await screen.findByRole("heading", { name: "We couldn't find that page" })).toBeInTheDocument();
  });

  it("shows the read-only banner with the end time on a business opened under a grant", async () => {
    server.reply(ME, support);
    server.reply(GRANTS, { status: 200, body: { grants: [grant] } });
    server.reply(HOME, home);
    open("/b/b-1/home");
    expect(await screen.findByText("Support view · read-only · ends 25-Oct-2099, 14:20")).toBeInTheDocument();
    expect(screen.getByText("Vashi Essentials")).toBeInTheDocument();
    // A support user's Settings has no Support access link (owners and admins only).
    expect(screen.queryByRole("link", { name: "Support access" })).toBeNull();
  });

  it("shows no banner to a member", async () => {
    server.reply(ME, { status: 200, body: { businesses: [{ business_id: "b-1", display_name: "Vashi Essentials", gstin: null, role: "owner" }], is_support: false } });
    server.reply(HOME, home);
    open("/b/b-1/home");
    expect(await screen.findByText("Vashi Essentials")).toBeInTheDocument();
    expect(screen.queryByText(/Support view/)).toBeNull();
    expect(server.paths()).not.toContain(GRANTS);
  });

  it("refetches just after the first end still ahead", () => {
    const now = Date.parse("2026-11-03T10:00:00Z");
    expect(msUntilFirst(["2026-11-03T09:00:00Z", "2026-11-03T10:00:05Z", "2026-11-03T11:00:00Z"], now)).toBe(6000);
    expect(msUntilFirst(["2026-11-03T09:00:00Z"], now)).toBe(false);
    expect(msUntilFirst(["2099-01-01T00:00:00Z"], now)).toBe(2 ** 31 - 1);
  });
});
