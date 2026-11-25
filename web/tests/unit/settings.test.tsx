import { fireEvent, render, screen } from "@testing-library/react";
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

describe("business setup page", () => {
  it("holds the filing frequency on this one page, and sends the old addresses here", async () => {
    server.reply(CHANNELS, channels);
    server.reply(FILING, filing({ frequency: "monthly", effective_from: "2026-04-01" }));
    window.history.replaceState(null, "", "/b/b-1/settings/filing"); // the old address
    server.reply(ME, me("owner"));
    render(<App />);
    expect(await screen.findByRole("heading", { level: 1, name: "Business setup" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/b/b-1/settings");
    expect(await screen.findByRole("heading", { level: 2, name: "Filing frequency" })).toBeInTheDocument();
    expect(await screen.findByText(/Every month, from/)).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1); // one page, one main heading
    // While a form is open the sub-menu gives way (one laptop screen, #404); Back shows it again.
    expect(screen.queryByRole("link", { name: "Audit log" })).toBeNull();
    fireEvent.click(screen.getByRole("link", { name: "Back to Business setup" }));
    expect(await screen.findByRole("link", { name: "Audit log" })).toHaveAttribute("href", "/b/b-1/settings/audit");
    expect(screen.getByRole("link", { name: "Support access" })).toBeInTheDocument();
  });

  it("sends the old business details address here too", async () => {
    server.reply(CHANNELS, channels);
    server.reply(FILING, filing(null));
    window.history.replaceState(null, "", "/b/b-1/settings/company");
    server.reply(ME, me("owner"));
    render(<App />);
    expect(await screen.findByRole("heading", { level: 1, name: "Business setup" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/b/b-1/settings");
  });

  it("leaves out the audit log and support access for a role that cannot open them", async () => {
    server.reply(CHANNELS, channels);
    server.reply(FILING, filing(null));
    open("staff");
    expect(await screen.findByText("You haven't chosen a filing frequency yet.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Audit log" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Support access" })).toBeNull();
    expect(screen.getByRole("link", { name: "Two-step sign-in" })).toBeInTheDocument();
  });
});
