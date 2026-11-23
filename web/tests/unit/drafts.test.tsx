import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { fakeApi } from "./fakeApi";

vi.mock("../../src/features", () => ({ FEATURES: { invoicing: true } })); // R2 screens

const DRAFTS = "/api/v1/b/b-1/drafts";
const me = (role = "owner") => ({ status: 200, body: { businesses: [{ business_id: "b-1", display_name: "Vashi Essentials", gstin: null, role }] } });
const draft = (over: Record<string, unknown> = {}) => ({
  id: "d-1", kind: "invoice", version: 2, customer_id: "c-1", cash_buyer: null, bill_to: { name: "Sharma Traders" }, ship_to: null,
  doc_date: "2026-11-20", invoice_discount: "0.00", charges: [], eway: null, customer_collects: false, ship_to_third_party: false,
  pos_override: null, pos_override_reason: null, lines: [], total: "1180.00", ready: true, computed_at: "2026-11-20T10:00:00Z",
  created_at: "2026-11-20T09:00:00Z", updated_at: "2026-11-20T10:00:00Z", ...over,
});

let server: ReturnType<typeof fakeApi>;
beforeEach(() => {
  resetSessionForTests();
  server = fakeApi();
  server.reply("/api/v1/auth/refresh", { status: 200, body: { access_token: "t", expires_in: 3600 } });
});
afterEach(() => vi.unstubAllGlobals());
const open = (path: string, role = "owner") => {
  server.reply("/api/v1/me/businesses", me(role), me(role));
  window.history.replaceState(null, "", path);
  render(<App />);
};

describe("draft invoices", () => {
  it("lists open invoice drafts with buyer, total and whether each is ready, and pages with the cursor", async () => {
    server.reply(
      DRAFTS,
      { status: 200, body: { items: [draft(), draft({ id: "d-2", customer_id: null, bill_to: null, cash_buyer: { name: null, state_code: "19" }, total: null, ready: false })], has_more: true, next_cursor: "abc" } },
      { status: 200, body: { items: [draft({ id: "d-3", bill_to: null, ready: null, doc_date: null })], has_more: false, next_cursor: null } },
    );
    open("/b/b-1/drafts");
    const first = await screen.findByRole("link", { name: "Sharma Traders" });
    expect(first).toHaveAttribute("href", "/b/b-1/invoices/d-1");
    expect(screen.getByText("₹1,180.00")).toBeInTheDocument();
    expect(screen.getByText("Ready to finalize")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Cash sale" })).toHaveAttribute("href", "/b/b-1/invoices/d-2");
    expect(screen.getByText("Needs fixes")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByRole("link", { name: "No buyer yet" })).toBeInTheDocument();
    expect(screen.getByText("Not checked yet")).toBeInTheDocument();
    const asked = server.sent.filter((s) => s.path === DRAFTS).map((s) => new URL(s.url).searchParams);
    expect(asked.map((q) => [q.get("kind"), q.get("cursor")])).toEqual([["invoice", null], ["invoice", "abc"]]);
  });

  it("says there are none, with a way to start one", async () => {
    server.reply(DRAFTS, { status: 200, body: { items: [], has_more: false, next_cursor: null } });
    open("/b/b-1/drafts");
    expect(await screen.findByText(/No drafts\./)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Start a new invoice" })).toHaveAttribute("href", "/b/b-1/invoices/new");
  });

  it("is not offered to a role that can't make invoices", async () => {
    open("/b/b-1/drafts", "ca");
    expect(await screen.findByText(/couldn't find that page/i)).toBeInTheDocument();
    expect(server.paths()).not.toContain(DRAFTS);
  });
});
