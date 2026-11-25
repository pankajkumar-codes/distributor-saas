import { act, fireEvent, render, screen } from "@testing-library/react";
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
// What GET /documents/{id} adds to the document: the buyer, the lines with their tax split, and the totals block.
const docFull = {
  ...doc, fy: "2026-27", gstin: "19ABCDE1234F1Z5", supply_class: "B2B", pos_state_code: "19", is_inter_state: false, customer_id: "c-1", counterparty_name: "Sharma Traders",
  due_date: null, taxable_total: "1000.00", cgst_total: "90.00", sgst_total: "90.00", utgst: false, igst_total: "0.00", round_off: "0.00", finalized_at: "2026-11-18T10:00:00Z",
  buyer: { name: "Sharma Traders", gstin: "19AAAAA0000A1Z5", address: ["12 Market Road", "Howrah 711101"], state: "West Bengal (19)" }, ship_to: null, place_of_supply: "West Bengal (19)", pos_basis: "delivery", pos_override_reason: null,
  lines: [{ no: "1", description: "Aloe Vera Gel", hsn: "3304", quantity: "10", uqc: "PCS", unit_price: "100.00", gross: "1000.00", discount: null, taxable: "1000.00",
    taxes: [{ component: "CGST", rate: "9", amount: "90.00" }, { component: "SGST", rate: "9", amount: "90.00" }], total: "1180.00" }],
  gross_total: "1000.00", line_discount_total: "0.00", invoice_discount: "0.00", charges_total: "0.00", charges_label: null, cess_total: "0.00", amount_in_words: "One thousand one hundred eighty rupees only",
}; // fmt: skip
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
    expect(await screen.findByText(/No stock on hand\. You can still sell it/)).toBeInTheDocument();
    expect(screen.getByText(/has no selling price yet/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create practice invoice" })).toBeEnabled();
  });

  it("finalizes a practice invoice, opens it, says so, and downloads its PDF", async () => {
    const detail = (pdf: Record<string, unknown>) => ({ ...docFull, stock_movements: 1, pdf });
    server.reply(`POST ${ONE}/finalize`, { status: 200, body: doc });
    server.reply(`GET ${B}/documents/doc-1`, { status: 200, body: detail({ status: "none" }) }, { status: 200, body: detail({ status: "ready", job_id: "j-1", attempt: 1, url: "https://files.example/p.pdf" }) });
    server.reply(`POST ${B}/documents/doc-1/pdf`, { status: 202, body: { job_id: "j-1", attempt: 1 } });
    open();
    fireEvent.click(await screen.findByRole("button", { name: "Create practice invoice" }));
    expect(await screen.findByText("Invoice PI-2026-27-0001")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/b/b-1/documents/doc-1");
    expect(screen.getByText(/not a tax invoice/)).toBeInTheDocument();
    const fin = server.sent.find((s) => s.path === `${ONE}/finalize`)!;
    expect(fin.headers.get("If-Match")).toBe("2");
    expect(fin.headers.get("Idempotency-Key")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Download practice PDF" }));
    const link = await screen.findByRole("link", { name: "Open the PDF" });
    expect(link).toHaveAttribute("href", "https://files.example/p.pdf");
  });

  it("saves unsaved changes and then creates the invoice from the saved version, in one press", async () => {
    server.reply(`PUT ${ONE}`, { status: 200, body: draft({ version: 3 }) });
    server.reply(`POST ${ONE}/finalize`, { status: 200, body: doc });
    server.reply(`GET ${B}/documents/doc-1`, { status: 200, body: { ...docFull, stock_movements: 1, pdf: { status: "none" } } });
    open();
    fireEvent.change(await screen.findByLabelText(/^Quantity of /), { target: { value: "11" } });
    fireEvent.click(screen.getByRole("button", { name: "Create practice invoice" }));
    expect(await screen.findByText("Invoice PI-2026-27-0001")).toBeInTheDocument();
    expect(server.sent.find((s) => s.path === ONE && s.method === "PUT")!.headers.get("If-Match")).toBe("2");
    expect(server.sent.find((s) => s.path === `${ONE}/finalize`)!.headers.get("If-Match")).toBe("3");
  });

  it("saves once and creates once when Create is pressed twice quickly", async () => {
    server.reply(`PUT ${ONE}`, { status: 200, body: draft({ version: 3 }) }, { status: 409, body: { error: { code: "stale_record", message: "changed" } } });
    server.reply(`POST ${ONE}/finalize`, { status: 200, body: doc });
    server.reply(`GET ${B}/documents/doc-1`, { status: 200, body: { ...docFull, stock_movements: 1, pdf: { status: "none" } } });
    open();
    fireEvent.change(await screen.findByLabelText(/^Quantity of /), { target: { value: "11" } });
    const create = screen.getByRole("button", { name: "Create practice invoice" });
    act(() => {
      create.click(); // both presses land before the page has re-rendered, as with a fast double click
      create.click();
    });
    expect(await screen.findByText("Invoice PI-2026-27-0001")).toBeInTheDocument();
    expect(server.sent.filter((s) => s.path === ONE && s.method === "PUT")).toHaveLength(1);
    expect(server.sent.filter((s) => s.path === `${ONE}/finalize`)).toHaveLength(1);
  });

  it("after a failed finalize, pressing Create again does not save again and finalizes with the same key", async () => {
    server.reply(`PUT ${ONE}`, { status: 200, body: draft({ version: 3 }) });
    server.reply(`POST ${ONE}/finalize`, { status: 503 }, { status: 200, body: doc });
    server.reply(`GET ${B}/documents/doc-1`, { status: 200, body: { ...docFull, stock_movements: 1, pdf: { status: "none" } } });
    open();
    fireEvent.change(await screen.findByLabelText(/^Quantity of /), { target: { value: "11" } });
    fireEvent.click(screen.getByRole("button", { name: "Create practice invoice" }));
    expect(await screen.findByText(/Something went wrong on our side/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Create practice invoice" }));
    expect(await screen.findByText("Invoice PI-2026-27-0001")).toBeInTheDocument();
    expect(server.sent.filter((s) => s.path === ONE && s.method === "PUT")).toHaveLength(1);
    const [first, second] = server.sent.filter((s) => s.path === `${ONE}/finalize`);
    expect(second.headers.get("Idempotency-Key")).toBe(first.headers.get("Idempotency-Key"));
    expect(second.headers.get("If-Match")).toBe("3");
  });

  it("does not create the invoice when the save is refused", async () => {
    server.reply(`PUT ${ONE}`, { status: 422, body: { error: { code: "invalid", message: "Check the quantity" } } });
    open();
    fireEvent.change(await screen.findByLabelText(/^Quantity of /), { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: "Create practice invoice" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(server.sent.filter((s) => s.path === `${ONE}/finalize`)).toHaveLength(0);
  });

  it("asks for the PDF once when the button is pressed twice quickly", async () => {
    server.reply(`GET ${B}/documents/doc-1`, { status: 200, body: { ...docFull, stock_movements: 1, pdf: { status: "none" } } });
    server.reply(`POST ${B}/documents/doc-1/pdf`, { status: 202, body: { job_id: "j-1", attempt: 1 } });
    window.history.replaceState(null, "", "/b/b-1/documents/doc-1");
    render(<App />);
    const button = await screen.findByRole("button", { name: "Download practice PDF" });
    fireEvent.click(button);
    fireEvent.click(button);
    await vi.waitFor(() => expect(server.sent.filter((s) => s.method === "POST" && s.path === `${B}/documents/doc-1/pdf`)).toHaveLength(1));
    await new Promise((r) => setTimeout(r, 50));
    expect(server.sent.filter((s) => s.method === "POST" && s.path === `${B}/documents/doc-1/pdf`)).toHaveLength(1);
  });

  it("shows a PDF that is already ready when the invoice is opened later", async () => {
    server.reply(`GET ${B}/documents/doc-1`, { status: 200, body: { ...docFull, stock_movements: 1, pdf: { status: "ready", job_id: "j-1", attempt: 1, url: "https://files.example/p.pdf" } } });
    window.history.replaceState(null, "", "/b/b-1/documents/doc-1");
    render(<App />);
    expect(await screen.findByRole("link", { name: "Open the PDF" })).toBeInTheDocument();
    expect(screen.getByText("Practice invoice.")).toBeInTheDocument();
  });

  it("lists issued invoices, practice ones marked", async () => {
    server.reply(`${B}/documents`, { status: 200, body: { documents: [{ ...doc, counterparty_name: "Sharma Traders" }], has_more: false } });
    window.history.replaceState(null, "", "/b/b-1/documents");
    render(<App />);
    expect(await screen.findByRole("link", { name: "PI-2026-27-0001" })).toHaveAttribute("href", "/b/b-1/documents/doc-1");
    expect(screen.getByText("Practice")).toBeInTheDocument();
    expect(screen.getByText("₹1,180.00")).toBeInTheDocument();
  });

  it("says finalizing is not switched on when the server answers not found", async () => {
    server.reply(`POST ${ONE}/finalize`, { status: 404, body: { error: { code: "not_found", message: "" } } });
    open();
    fireEvent.click(await screen.findByRole("button", { name: "Create practice invoice" }));
    expect(await screen.findByText(/Finalizing isn't switched on for your business yet/)).toBeInTheDocument();
  });

  it("points to the plan when the free invoices are used", async () => {
    server.reply(`POST ${ONE}/finalize`, { status: 402, body: { error: { code: "invoice_plan_required", message: "Choose the plan" } } });
    open();
    fireEvent.click(await screen.findByRole("button", { name: "Create practice invoice" }));
    expect(await screen.findByRole("link", { name: "See the invoicing plan" })).toHaveAttribute("href", "/b/b-1/settings/plan");
  });
});


describe("the issued invoice page", () => {
  const show = (body: Record<string, unknown>) => {
    server.reply(`GET ${B}/documents/doc-1`, { status: 200, body: { ...docFull, stock_movements: 1, pdf: { status: "none" }, ...body } });
    window.history.replaceState(null, "", "/b/b-1/documents/doc-1");
    render(<App />);
  };

  it("shows the buyer, each line, the CGST and SGST split and the totals as the server stored them", async () => {
    show({});
    expect(await screen.findByText("Invoice PI-2026-27-0001")).toBeInTheDocument();
    expect(screen.getByText(/Sharma Traders · GSTIN 19AAAAA0000A1Z5/)).toBeInTheDocument();
    expect(screen.getByText(/12 Market Road, Howrah 711101/)).toBeInTheDocument();
    expect(screen.getByText(/West Bengal \(19\) · Within the state/)).toBeInTheDocument();
    const row = screen.getByRole("row", { name: /Aloe Vera Gel/ });
    expect(row).toHaveTextContent("HSN 3304");
    expect(row).toHaveTextContent("10 PCS");
    expect(row).toHaveTextContent("CGST 9% ₹90.00");
    expect(row).toHaveTextContent("SGST 9% ₹90.00");
    expect(row).toHaveTextContent("₹1,180.00");
    expect(screen.getByText("CGST").nextElementSibling).toHaveTextContent("₹90.00");
    expect(screen.getByText("SGST").nextElementSibling).toHaveTextContent("₹90.00");
    expect(screen.queryByText("IGST")).not.toBeInTheDocument();
    expect(screen.queryByText("Round off")).not.toBeInTheDocument(); // zero amounts are left out
    expect(screen.getByText("One thousand one hundred eighty rupees only")).toBeInTheDocument();
  });

  it("labels a practice invoice as one, and offers the practice PDF", async () => {
    show({});
    expect(await screen.findByText(/Practice invoice\./)).toBeInTheDocument();
    expect(screen.getByText(/Practice · not for customers/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download practice PDF" })).toBeEnabled();
  });

  it("shows IGST for an inter-state invoice, a cash sale, discounts, charges and a round off", async () => {
    show({
      is_practice: false, is_inter_state: true, igst_total: "180.00", cgst_total: "0.00", sgst_total: "0.00", round_off: "-0.40", line_discount_total: "50.00", charges_total: "25.00", charges_label: "Freight",
      customer_id: null, counterparty_name: null, buyer: null, ship_to: { address: ["Dock 4"], state: "Bihar (10)" },
      lines: [{ ...docFull.lines[0], discount: "50.00", taxes: [{ component: "IGST", rate: "18", amount: "180.00" }] }],
    });
    expect(await screen.findByText("Cash sale")).toBeInTheDocument();
    expect(screen.queryByText(/Practice invoice\./)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download PDF" })).toBeInTheDocument();
    expect(screen.getByText("IGST").nextElementSibling).toHaveTextContent("₹180.00");
    expect(screen.queryByText("CGST")).not.toBeInTheDocument();
    expect(screen.getByText("Freight").nextElementSibling).toHaveTextContent("₹25.00");
    expect(screen.getByText("Line discounts").nextElementSibling).toHaveTextContent("₹50.00");
    expect(screen.getByText("Round off").nextElementSibling).toHaveTextContent("-₹0.40");
    expect(screen.getByText(/Dock 4, Bihar \(10\)/)).toBeInTheDocument();
  });

  it.each([
    [{}, "Where the goods are delivered."],
    [{ pos_basis: "third_party" }, /goods went to another person on the buyer's direction \("Goods go to a third party, not the buyer" was ticked\)/],
    [{ pos_basis: "customer_collects" }, /the buyer collects the goods .* CA to confirm/],
    [{ pos_basis: "buyer_address" }, "The buyer has no GSTIN: their delivery address, or billing address if none."],
    [{ pos_basis: "override", pos_override_reason: "Goods handed over in Kolkata" }, "Chosen by hand on the draft. Reason given: Goods handed over in Kolkata"],
  ])("says why the place of supply was chosen (%o)", async (body, text) => {
    show(body);
    expect(await screen.findByText(text)).toBeInTheDocument();
  });
});
