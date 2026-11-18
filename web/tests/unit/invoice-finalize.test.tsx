import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { fakeApi } from "./fakeApi";

vi.mock("../../src/features", () => ({ FEATURES: { invoicing: true } })); // R2 screens

const B = "/api/v1/b/b-1";
const ONE = `${B}/drafts/d-1`;
const draft = (over: Record<string, unknown> = {}) => ({
  id: "d-1", kind: "invoice", version: 2, customer_id: "c-1", cash_buyer: null, bill_to: { name: "Sharma Traders" }, ship_to: null, doc_date: null,
  invoice_discount: "0.00", charges: [], eway: null, customer_collects: false, ship_to_third_party: false, pos_override: null, pos_override_reason: null,
  lines: [{ id: "l-1", line_no: 1, product_id: "p-1", quantity: "10", unit_price: "0.00", discount_kind: null, discount_value: null }],
  total: "1180.00", ready: true, computed_at: "2026-11-09T10:00:00Z", created_at: "2026-11-09T10:00:00Z", updated_at: "2026-11-09T10:00:00Z", computation: null, ...over,
}); // fmt: skip
const product = { id: "p-1", name: "Aloe Vera Gel", hsn: "3304", code: "AVG", sale_rate: "0.00", status: "active", version: 1, warnings: [] };
const doc = { id: "doc-1", draft_id: "d-1", kind: "invoice", is_practice: true, doc_number: "PI-2026-27-0001", doc_date: "2026-11-18", doc_total: "1180.00" };
const stockItem = (id: string) => ({ product_id: id, code: "AVG", name: "Aloe Vera Gel", uqc: "PCS", status: "active", sale_rate: "0.00", price_needed: true, on_hand: "0.000", no_stock: true });

let server: ReturnType<typeof fakeApi>;
beforeEach(() => {
  resetSessionForTests();
  server = fakeApi();
  server.reply("/api/v1/auth/refresh", { status: 200, body: { access_token: "t", expires_in: 3600 } });
  server.reply("/api/v1/me/businesses", { status: 200, body: { businesses: [{ business_id: "b-1", display_name: "Vashi Essentials", gstin: null, role: "owner" }] } });
  server.reply("/api/v1/refdata/state-codes", { status: 200, body: { on: "2026-11-09", states: [] } });
  server.reply(ONE, { status: 200, body: draft() });
  server.reply(`${B}/products/p-1`, { status: 200, body: product });
  server.reply(`${B}/stock`, { status: 200, body: { items: [stockItem("p-1")], has_more: false } }, { status: 200, body: { items: [stockItem("p-1")], has_more: false } });
});
afterEach(() => vi.unstubAllGlobals());
const open = () => {
  window.history.replaceState(null, "", "/b/b-1/invoices/d-1");
  render(<App />);
};

describe("a sales invoice from the catalog", () => {
  it("warns about no stock and a missing price without blocking anything", async () => {
    open();
    expect(await screen.findByText(/No stock on hand for this product. You can still sell it/)).toBeInTheDocument();
    expect(screen.getByText(/has no selling price yet/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Finalize invoice" })).toBeEnabled();
  });

  it("finalizes a practice invoice, says so, and downloads its PDF", async () => {
    server.reply(`POST ${ONE}/finalize`, { status: 200, body: doc });
    server.reply(`POST ${B}/documents/doc-1/pdf`, { status: 202, body: { job_id: "j-1", attempt: 1 } });
    server.reply(`GET ${B}/documents/doc-1/pdf/j-1`, { status: 200, body: { status: "ready", url: "https://files.example/p.pdf" } });
    open();
    fireEvent.click(await screen.findByRole("button", { name: "Finalize invoice" }));
    expect(await screen.findByText("Invoice PI-2026-27-0001")).toBeInTheDocument();
    expect(screen.getByText(/not a tax invoice/)).toBeInTheDocument();
    const fin = server.sent.find((s) => s.path === `${ONE}/finalize`)!;
    expect(fin.headers.get("If-Match")).toBe("2");
    expect(fin.headers.get("Idempotency-Key")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Download practice PDF" }));
    const link = await screen.findByRole("link", { name: "Open the PDF" });
    expect(link).toHaveAttribute("href", "https://files.example/p.pdf");
  });

  it("says finalizing is not switched on when the server answers not found", async () => {
    server.reply(`POST ${ONE}/finalize`, { status: 404, body: { error: { code: "not_found", message: "" } } });
    open();
    fireEvent.click(await screen.findByRole("button", { name: "Finalize invoice" }));
    expect(await screen.findByText(/Finalizing isn't switched on for your business yet/)).toBeInTheDocument();
  });

  it("points to the plan when the free invoices are used", async () => {
    server.reply(`POST ${ONE}/finalize`, { status: 402, body: { error: { code: "invoice_plan_required", message: "Choose the plan" } } });
    open();
    fireEvent.click(await screen.findByRole("button", { name: "Finalize invoice" }));
    expect(await screen.findByRole("link", { name: "See the invoicing plan" })).toHaveAttribute("href", "/b/b-1/settings/plan");
  });
});
