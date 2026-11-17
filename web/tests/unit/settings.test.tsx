import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { fakeApi } from "./fakeApi";

const REFRESH = "/api/v1/auth/refresh";
const ME = "/api/v1/me/businesses";
const CHANNELS = "/api/v1/b/b-1/channels";
const FILING = "/api/v1/b/b-1/filing-profile";
const me = (role: string) => ({ status: 200, body: { businesses: [{ business_id: "b-1", display_name: "Vashi Essentials", gstin: "19ABCDE1234F1Z5", role }] } });
const channels = { status: 200, body: { amazon: true, flipkart: false, meesho: true, own_invoices: true, answered: true } };
const filing = (current: unknown) => ({
  status: 200,
  body: { gstin: "19ABCDE1234F1Z5", current, history: [], warnings: [], window: { for_quarter: "2026-10-01", open_until: "2026-12-31" } },
});

let server: ReturnType<typeof fakeApi>;
beforeEach(() => {
  resetSessionForTests();
  server = fakeApi();
  server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
});
afterEach(() => vi.unstubAllGlobals());

function open(role = "owner") {
  server.reply(ME, me(role), me(role));
  window.history.replaceState(null, "", "/b/b-1/settings");
  render(<App />);
}

describe("business setup front page", () => {
  it("shows what is set now and links to the page where each is changed", async () => {
    server.reply(CHANNELS, channels);
    server.reply(FILING, filing({ frequency: "monthly", effective_from: "2026-04-01" }));
    open();
    expect(await screen.findByRole("heading", { level: 1, name: "Business setup" })).toBeInTheDocument();
    expect(await screen.findByText("Amazon, Meesho, Your own sales invoices")).toBeInTheDocument();
    expect(await screen.findByText(/Every month, from/)).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Business details" })).getByText(/GSTIN 19ABCDE1234F1Z5/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Change how often you file" })).toHaveAttribute("href", "/b/b-1/settings/filing");
    expect(screen.getByRole("link", { name: "Change where you sell" })).toHaveAttribute("href", "/b/b-1/settings/company");
    expect(screen.getByRole("link", { name: "Audit log" })).toHaveAttribute("href", "/b/b-1/settings/audit");
    expect(screen.getByRole("link", { name: "Support access" })).toBeInTheDocument();
  });

  it("says so when nothing is chosen yet, and when a value could not be loaded, and still links", async () => {
    server.reply(CHANNELS, { status: 200, body: { amazon: false, flipkart: false, meesho: false, own_invoices: false, answered: false } });
    server.reply(FILING, { status: 500, body: { error: { code: "internal", message: "" } } });
    open();
    expect(await screen.findByText("You haven't said where you sell yet.")).toBeInTheDocument();
    expect(await screen.findByText(/We couldn't load this/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Change how often you file" })).toBeInTheDocument();
  });

  it("leaves out the audit log and support access for a role that cannot open them", async () => {
    server.reply(CHANNELS, channels);
    server.reply(FILING, filing(null));
    open("staff");
    expect(await screen.findByText("You haven't chosen how often you file yet.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Audit log" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Support access" })).toBeNull();
    expect(screen.getByRole("link", { name: "Two-step sign-in" })).toBeInTheDocument();
  });
});
