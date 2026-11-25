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

const DOCS = "/api/v1/b/b-1/documents";
const doc = (n: number) => ({ id: `doc-${n}`, doc_number: `PR-${String(n).padStart(4, "0")}`, doc_date: "2026-12-07", counterparty_name: "Arora Wholesale", doc_total: "8000.40", is_practice: true });

describe("issued invoices", () => {
  it("pages eight at a time with Previous and Next, practice ones marked", async () => {
    server.reply(DOCS, { status: 200, body: { documents: [1, 2, 3, 4, 5, 6, 7, 8].map(doc), has_more: true } }, { status: 200, body: { documents: [doc(9)], has_more: false } });
    open("/b/b-1/documents");
    expect(await screen.findByRole("link", { name: "PR-0001" })).toHaveAttribute("href", "/b/b-1/documents/doc-1");
    expect(screen.getAllByText("Practice")).toHaveLength(8);
    expect(screen.getByText("Invoices 1–8")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByRole("link", { name: "PR-0009" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "PR-0001" })).toBeNull();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
    const asked = server.sent.filter((s) => s.path === DOCS).map((s) => new URL(s.url).searchParams);
    expect(asked.map((q) => [q.get("limit"), q.get("offset")])).toEqual([["8", "0"], ["8", "8"]]);
  });

  it("says none are issued yet", async () => {
    server.reply(DOCS, { status: 200, body: { documents: [], has_more: false } });
    open("/b/b-1/documents");
    expect(await screen.findByText(/No invoices issued yet/)).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "New invoice" }).find((a) => a.classList.contains("btn-primary"))).toHaveAttribute("href", "/b/b-1/invoices/new");
  });
});

describe("draft invoices", () => {
  it("lists open invoice drafts with buyer, total and whether each is ready, a page at a time with the cursor", async () => {
    server.reply(
      DRAFTS,
      { status: 200, body: { items: [draft(), draft({ id: "d-2", customer_id: null, bill_to: null, cash_buyer: { name: null, state_code: "19" }, total: null, ready: false })], has_more: true, next_cursor: "abc" } },
      { status: 200, body: { items: [draft({ id: "d-3", bill_to: null, ready: null, doc_date: null })], has_more: false, next_cursor: null } },
    );
    open("/b/b-1/drafts");
    const first = await screen.findByRole("link", { name: "Sharma Traders" });
    expect(first).toHaveAttribute("href", "/b/b-1/invoices/d-1");
    expect(screen.getByText("₹1,180.00")).toBeInTheDocument();
    expect(screen.getByText("Ready to create")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Cash sale" })).toHaveAttribute("href", "/b/b-1/invoices/d-2");
    expect(screen.getByText("Needs fixes")).toBeInTheDocument();
    expect(screen.getByText("Drafts 1–2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByRole("link", { name: "No buyer yet" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Sharma Traders" })).toBeNull(); // a page replaces the last, the screen never grows
    expect(screen.getByText("Not checked yet")).toBeInTheDocument();
    expect(screen.getByText("Day you create it")).toBeInTheDocument(); // no date yet
    expect(screen.getByText("Drafts 9–9")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    expect(await screen.findByRole("link", { name: "Sharma Traders" })).toBeInTheDocument(); // the first cursor again
    const asked = server.sent.filter((s) => s.path === DRAFTS).map((s) => new URL(s.url).searchParams);
    expect(asked.slice(0, 2).map((q) => [q.get("kind"), q.get("limit"), q.get("cursor")])).toEqual([["invoice", "8", null], ["invoice", "8", "abc"]]);
    expect(asked.slice(2).every((q) => q.get("cursor") === null)).toBe(true);
  });

  it("says there are none, with a way to start one", async () => {
    server.reply(DRAFTS, { status: 200, body: { items: [], has_more: false, next_cursor: null } });
    open("/b/b-1/drafts");
    expect(await screen.findByText(/No drafts\./)).toBeInTheDocument();
    for (const link of screen.getAllByRole("link", { name: "Start a new invoice" })) expect(link).toHaveAttribute("href", "/b/b-1/invoices/new");
  });

  it("is not offered to a role that can't make invoices", async () => {
    open("/b/b-1/drafts", "ca");
    expect(await screen.findByText(/couldn't find that page/i)).toBeInTheDocument();
    expect(server.paths()).not.toContain(DRAFTS);
  });
});
