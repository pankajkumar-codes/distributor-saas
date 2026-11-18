import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { fakeApi } from "./fakeApi";

const CH = "/api/v1/b/b-1/channels";
const mine = (role = "owner") => ({ status: 200, body: { businesses: [{ business_id: "b-1", display_name: "Vaashi Essentials", gstin: "19ABCDE1234F1Z5", role }] } });
const ch = (over: Record<string, boolean> = {}) => ({ status: 200, body: { amazon: true, flipkart: false, meesho: false, own_invoices: false, answered: true, ...over } });

let server: ReturnType<typeof fakeApi>;
beforeEach(() => {
  resetSessionForTests();
  server = fakeApi();
  server.reply("/api/v1/auth/refresh", { status: 200, body: { access_token: "t", expires_in: 3600 } });
});
afterEach(() => vi.unstubAllGlobals());

function open(role = "owner") {
  server.reply("/api/v1/me/businesses", mine(role));
  window.history.replaceState(null, "", "/b/b-1/onboarding/marketplaces");
  render(<App />);
}

describe("Marketplaces you sell on", () => {
  it("shows what is saved and saves a change, as in Business setup", async () => {
    server.reply(CH, ch(), ch({ meesho: true }));
    open();
    expect(await screen.findByRole("heading", { level: 1, name: "Marketplaces you sell on" })).toBeInTheDocument();
    await vi.waitFor(() => expect(screen.getByRole("checkbox", { name: "Amazon" })).toBeChecked());
    fireEvent.click(screen.getByRole("checkbox", { name: "Meesho" }));
    fireEvent.click(screen.getByRole("button", { name: "Save where you sell" }));
    expect(await screen.findByText("Saved. Deadlines updated.")).toBeInTheDocument();
    expect(server.sent.find((s) => s.path === CH && s.method === "PUT")?.body).toEqual({ amazon: true, flipkart: false, meesho: true, own_invoices: false });
  });

  it("leaves the boxes off for a role that cannot change them", async () => {
    server.reply(CH, ch());
    open("ca");
    await vi.waitFor(() => expect(screen.getByRole("checkbox", { name: "Amazon" })).toBeChecked());
    expect(screen.getByRole("checkbox", { name: "Amazon" })).toBeDisabled();
  });
});
