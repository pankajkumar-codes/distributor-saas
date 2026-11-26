import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { resetFormKeysForTests } from "../../src/kit/formKey";
import { fakeApi } from "./fakeApi";

// Credit notes (#456, mocks v17 R.adjust and R.note). Made-up data.
const B = "/api/v1/b/b-1";
const base = {
  fy: "2026-27", gstin: "19ABCDE1234F1Z5", supply_class: "B2B", pos_state_code: "19", is_inter_state: false, customer_id: "c-1", counterparty_name: "Sharma Traders",
  due_date: null, utgst: false, igst_total: "0.00", round_off: "0.00", finalized_at: "2026-11-18T10:00:00Z", is_practice: true,
  buyer: { name: "Sharma Traders", gstin: "19AAAAA0000A1Z5", address: ["12 Market Road"], state: "West Bengal (19)" }, ship_to: null, place_of_supply: "West Bengal (19)",
  pos_basis: "delivery", pos_override_reason: null, gross_total: "1000.00", line_discount_total: "0.00", invoice_discount: "0.00", charges_total: "0.00", charges_label: null,
  cess_total: "0.00", stock_movements: 1, pdf: { status: "none" }, original: null, reason: null, stock_treatment: null, original_document_id: null, reason_code: null,
}; // fmt: skip
const line = (qty: string, taxable: string, tax: string, total: string) => ({
  no: "1", description: "Aloe Vera Gel", hsn: "3304", quantity: qty, uqc: "PCS", unit_price: "100.00", gross: taxable, discount: null, taxable,
  taxes: [{ component: "CGST", rate: "9", amount: tax }, { component: "SGST", rate: "9", amount: tax }], total,
}); // fmt: skip
const invoice = {
  ...base, id: "doc-1", draft_id: "d-1", kind: "invoice", doc_number: "PR-0042", doc_date: "2026-11-18", doc_total: "1180.00", taxable_total: "1000.00",
  cgst_total: "90.00", sgst_total: "90.00", lines: [line("10", "1000.00", "90.00", "1180.00")], amount_in_words: "One thousand one hundred eighty rupees only",
}; // fmt: skip
const note = {
  ...base, id: "cn-1", draft_id: "d-2", kind: "credit_note", doc_number: "PR-CN-0001", doc_date: "2026-11-20", doc_total: "236.00", taxable_total: "200.00",
  cgst_total: "18.00", sgst_total: "18.00", lines: [line("2", "200.00", "18.00", "236.00")], amount_in_words: "Two hundred thirty-six rupees only",
  original: { number: "PR-0042", date: "2026-11-18" }, original_document_id: "doc-1", reason: "Goods returned", reason_code: "goods_returned", stock_treatment: "restock",
}; // fmt: skip
const credit = (notes: unknown[] = [], remainingQty = "10", remaining = "1180.00") => ({
  invoice_id: "doc-1", doc_number: "PR-0042", is_practice: true, last_date: "2027-11-30", remaining_total: remaining, notes,
  reasons: { goods_returned: "Goods returned", value_too_high: "Taxable value or tax charged too high", deficient: "Goods or services deficient" },
  lines: [{ original_line_id: "l-1", line_no: 1, name: "Aloe Vera Gel", hsn: "3304", uqc: "PCS", rate: "18", quantity: "10", remaining_quantity: remainingQty,
    taxable: "1000.00", remaining_taxable: remainingQty === "10" ? "1000.00" : "800.00", remaining_tax: "144.00" }],
}); // fmt: skip

let server: ReturnType<typeof fakeApi>;
beforeEach(() => {
  resetSessionForTests();
  resetFormKeysForTests();
  server = fakeApi();
  server.reply("/api/v1/auth/refresh", { status: 200, body: { access_token: "t", expires_in: 3600 } });
  server.reply("/api/v1/me/businesses", { status: 200, body: { businesses: [{ business_id: "b-1", display_name: "Vashi Essentials", gstin: null, role: "owner" }] } });
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
const go = (path: string) => {
  window.history.replaceState(null, "", path);
  render(<App />);
};

describe("credit notes", () => {
  it("offers Adjust invoice on an issued invoice and lists its notes with what is left", async () => {
    server.reply(`GET ${B}/documents/doc-1`, { status: 200, body: invoice });
    server.reply(`GET ${B}/documents/doc-1/credit`, { status: 200, body: credit([{ id: "cn-1", doc_number: "PR-CN-0001", doc_date: "2026-11-20", doc_total: "236.00", is_practice: true, reason_code: "goods_returned" }], "8", "944.00") });
    go("/b/b-1/documents/doc-1");
    expect(await screen.findByRole("link", { name: "Adjust invoice" })).toHaveAttribute("href", "/b/b-1/documents/doc-1/adjust");
    const notes = await screen.findByRole("region", { name: "Credit notes" });
    expect(notes).toHaveTextContent("PR-CN-0001");
    expect(notes).toHaveTextContent("−₹236.00");
    expect(notes).toHaveTextContent(/Still on the invoice\s*₹944.00/);
  });

  it("credits returned goods by quantity with one key, then opens the note", async () => {
    server.reply(`GET ${B}/documents/doc-1`, { status: 200, body: invoice });
    server.reply(`GET ${B}/documents/doc-1/credit`, { status: 200, body: credit() });
    server.reply(`POST ${B}/documents/doc-1/credit-notes`, { status: 422, body: { error: { code: "credit_quantity_too_high", message: "At most 10 can be credited on this line", field: "lines.0.quantity" } } }, { status: 201, body: note });
    server.reply(`GET ${B}/documents/cn-1`, { status: 200, body: note });
    go("/b/b-1/documents/doc-1/adjust");
    const create = await screen.findByRole("button", { name: "Create practice credit note" });
    expect(create).toBeDisabled();
    expect(screen.getByText(/reverses the matching input tax credit/)).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Quantity to credit, Aloe Vera Gel" }), { target: { value: "12" } });
    fireEvent.click(screen.getByRole("radio", { name: "Returned and written off" }));
    fireEvent.click(create);
    expect(await screen.findByText("At most 10 can be credited on this line")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Quantity to credit, Aloe Vera Gel" }), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Create practice credit note" }));
    expect(await screen.findByRole("heading", { name: "Credit note issued PR-CN-0001" })).toBeInTheDocument();
    const posts = server.sent.filter((s) => s.method === "POST" && s.path === `${B}/documents/doc-1/credit-notes`);
    expect(posts).toHaveLength(2);
    expect(posts[1].body).toMatchObject({ reason: "goods_returned", stock_treatment: "write_off", lines: [{ original_line_id: "l-1", quantity: "2" }] });
    expect(posts[0].headers.get("Idempotency-Key")).toBe(posts[1].headers.get("Idempotency-Key"));
    expect(window.location.pathname).toBe("/b/b-1/documents/cn-1");
  });

  it("credits a price that was too high by taxable value, with no stock choice", async () => {
    server.reply(`GET ${B}/documents/doc-1`, { status: 200, body: invoice });
    server.reply(`GET ${B}/documents/doc-1/credit`, { status: 200, body: credit() });
    server.reply(`POST ${B}/documents/doc-1/credit-notes`, { status: 201, body: { ...note, reason_code: "value_too_high" } });
    server.reply(`GET ${B}/documents/cn-1`, { status: 200, body: note });
    go("/b/b-1/documents/doc-1/adjust");
    fireEvent.change(await screen.findByRole("combobox", { name: "Reason" }), { target: { value: "value_too_high" } });
    expect(screen.queryByRole("radio", { name: "Back to stock" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Taxable value to credit, Aloe Vera Gel" }), { target: { value: "150.50" } });
    fireEvent.click(screen.getByRole("button", { name: "Create practice credit note" }));
    await screen.findByRole("heading", { name: "Credit note issued PR-CN-0001" });
    const post = server.sent.find((s) => s.method === "POST" && s.path === `${B}/documents/doc-1/credit-notes`);
    expect(post?.body).toMatchObject({ reason: "value_too_high", stock_treatment: null, lines: [{ original_line_id: "l-1", taxable: "150.50" }] });
  });

  it("says when an invoice has been credited in full", async () => {
    server.reply(`GET ${B}/documents/doc-1`, { status: 200, body: invoice });
    server.reply(`GET ${B}/documents/doc-1/credit`, { status: 200, body: credit([], "0", "0.00") });
    go("/b/b-1/documents/doc-1/adjust");
    expect(await screen.findByText(/credited in full/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create practice credit note" })).not.toBeInTheDocument();
  });

  it("shows a note with its invoice, reason and stock, practice-marked, and no Adjust button", async () => {
    server.reply(`GET ${B}/documents/cn-1`, { status: 200, body: note });
    go("/b/b-1/documents/cn-1");
    expect(await screen.findByRole("heading", { name: "Credit note issued PR-CN-0001" })).toBeInTheDocument();
    const parties = screen.getByRole("region", { name: "Parties" });
    expect(screen.getByRole("link", { name: "PR-0042" })).toHaveAttribute("href", "/b/b-1/documents/doc-1");
    expect(parties).toHaveTextContent("Goods returned");
    expect(parties).toHaveTextContent("Back to stock");
    expect(screen.getByText(/Practice credit note\./)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Adjust invoice" })).not.toBeInTheDocument();
    expect(screen.getByText("Credited").nextElementSibling).toHaveTextContent("₹236.00");
    expect(server.paths()).not.toContain(`${B}/documents/cn-1/credit`);
  });
});
