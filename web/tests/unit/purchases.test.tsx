import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { confirmBody, isoDate, startingState } from "../../src/screens/purchases/ReviewPage";
import { fakeApi } from "./fakeApi";

vi.mock("../../src/features", () => ({ FEATURES: { invoicing: true } })); // R2 screens

const REFRESH = "/api/v1/auth/refresh";
const ME = "/api/v1/me/businesses";
const B = "/api/v1/b/b-1";
const me = (role = "owner") => ({ status: 200, body: { businesses: [{ business_id: "b-1", display_name: "Vashi Essentials", gstin: "19ABCDE1234F1Z5", role }] } });
const profile = (business_type: string | null) => ({ status: 200, body: { business_id: "b-1", business_type, version: 7 } });
const draft = (over: Record<string, unknown> = {}) => ({
  id: "d-1", file_id: "f-1", file_name: "bill.pdf", ordinal: 1, reader: "pdf_text_v1", pages: [1], doc_type: "Invoice",
  supplier_gstin: "19ABCDE1234F1ZX", doc_number: "SUP-1", doc_date: "03-07-2026", invoice_total: "236.00", unclear: [], decision: null,
  lines: [{ id: "l-1", line_no: 1, page: 1, hsn: "6109", quantity: "2", unit: "PCS", taxable_value: "200.00", gst_rate: "18", igst: null, cgst: "18.00", sgst: "18.00", cess: null, unclear: [] }],
  ...over,
});

let server: ReturnType<typeof fakeApi>;
beforeEach(() => {
  resetSessionForTests();
  server = fakeApi();
  server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
  server.reply(ME, me(), me());
});
afterEach(() => vi.unstubAllGlobals());

const open = (path: string) => {
  window.history.replaceState(null, "", path);
  render(<App />);
};

describe("purchase invoices", () => {
  it("asks for the business type first and saves it with the profile version", async () => {
    server.reply(`${B}/profile`, profile(null));
    open("/b/b-1/purchases");
    expect(await screen.findByRole("heading", { name: "First, what kind of business is this?" })).toBeInTheDocument();
    expect(screen.queryByLabelText(/Choose an invoice/)).toBeNull();
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    fireEvent.click(screen.getByLabelText("Retail"));
    server.reply(`PATCH ${B}/profile`, { status: 200, body: { profile: { business_id: "b-1", business_type: "retail", version: 8 }, warnings: [] } });
    server.reply(`GET ${B}/profile`, profile("retail"));
    server.reply(`${B}/purchase-files`, { status: 200, body: { files: [], has_more: false } });
    server.reply(`${B}/purchase-drafts`, { status: 200, body: { drafts: [], has_more: false } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByLabelText(/Choose an invoice/)).toBeInTheDocument();
    const patch = server.sent.find((s) => s.method === "PATCH")!;
    expect(patch.headers.get("If-Match")).toBe("7");
    expect(patch.body).toEqual({ business_type: "retail" });
  });

  it("lists what waits for a check and the files, once a type is chosen", async () => {
    server.reply(`${B}/profile`, profile("distributor"));
    server.reply(`${B}/purchase-files`, { status: 200, body: { files: [{ id: "f-9", file_name: "photo.jpg", size_bytes: 9, kind: "image", status: "rejected", reject_reason: "not_an_image", reject_message: "This file isn't a photo we can keep.", created_at: "2026-11-18T10:00:00Z" }], has_more: false } });
    server.reply(`${B}/purchase-drafts`, { status: 200, body: { drafts: [draft(), draft({ id: "d-2", reader: "none", doc_number: null })], has_more: false } });
    open("/b/b-1/purchases");
    expect(await screen.findByRole("link", { name: "Invoice SUP-1 from bill.pdf" })).toHaveAttribute("href", "/b/b-1/purchases/d-1");
    expect(screen.getByRole("link", { name: /Invoice to type in/ })).toBeInTheDocument();
    expect(screen.getByText(/photo.jpg: This file isn't a photo we can keep/)).toBeInTheDocument();
  });

  it("shows what was read, and confirms exactly what is on the screen", async () => {
    server.reply(`${B}/purchase-drafts/d-1`, { status: 200, body: draft() });
    server.reply(`${B}/products`, { status: 200, body: { items: [], has_more: false } });
    open("/b/b-1/purchases/d-1");
    expect(await screen.findByLabelText("Supplier GSTIN")).toHaveValue("19ABCDE1234F1ZX");
    expect(screen.getByLabelText("Invoice date")).toHaveValue("2026-07-03");
    expect(screen.getByLabelText("Quantity, line 1")).toHaveValue("2");
    fireEvent.change(screen.getByLabelText("Product name, line 1"), { target: { value: "Cotton tee" } });
    fireEvent.change(screen.getByLabelText("Product code, line 1"), { target: { value: "TEE-1" } });
    server.reply(`${B}/purchase-code-check`, { status: 200, body: { code: "TEE-1", available: true } });
    fireEvent.blur(screen.getByLabelText("Product code, line 1"));
    expect(await screen.findByText("This code is free.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Unit code (UQC), line 1"), { target: { value: "pcs" } });
    server.reply(`POST ${B}/purchase-drafts/d-1/confirm`, {
      status: 201,
      body: { review_id: "r-1", draft_id: "d-1", supplier_gstin: "19ABCDE1234F1ZX", supplier_name: null, doc_number: "SUP-1", doc_date: "2026-07-03", invoice_total: "236.00", line_count: 1, created_at: "2026-11-18T10:00:00Z", received: [{ line_no: 1, product_id: "p-1", created_product: true, price_needed: true }] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Confirm and add to my products" }));
    expect(await screen.findByText(/1 line added to your products and stock\. 1 still needs a selling price per 1 qty\./)).toBeInTheDocument();
    const sent = server.sent.find((s) => s.method === "POST" && s.path.endsWith("/confirm"))!.body as Record<string, unknown>;
    expect(sent).toMatchObject({ supplier_gstin: "19ABCDE1234F1ZX", doc_number: "SUP-1", doc_date: "2026-07-03", invoice_total: "236.00" });
    expect((sent.lines as Record<string, unknown>[])[0]).toMatchObject({
      draft_line_id: "l-1", product_id: null, product_name: "Cotton tee", hsn: "6109", quantity: "2", taxable_value: "200.00", gst_rate: "18", igst: "0", cgst: "18.00",
      new_item: { code: "TEE-1", uqc: "PCS", tax_category: "taxable", gst_rate: "18", rate_valid_from: "2026-07-03" },
    });
  });

  it("shows the server's refusal beside the field and keeps what was typed", async () => {
    server.reply(`${B}/purchase-drafts/d-1`, { status: 200, body: draft() });
    server.reply(`${B}/products`, { status: 200, body: { items: [], has_more: false } });
    open("/b/b-1/purchases/d-1");
    await screen.findByLabelText("Supplier GSTIN");
    server.reply(`POST ${B}/purchase-drafts/d-1/confirm`, { status: 422, body: { error: { code: "code_taken", message: "Another product already uses this code", field: "lines.0.code" } } });
    fireEvent.change(screen.getByLabelText("Product code, line 1"), { target: { value: "TEE-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm and add to my products" }));
    expect((await screen.findAllByText("Another product already uses this code")).length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Product code, line 1")).toHaveValue("TEE-1");
  });

  it("a draft nothing could be read from starts with one empty line and says to type it in", async () => {
    server.reply(`${B}/purchase-drafts/d-1`, { status: 200, body: draft({ reader: "none", lines: [], supplier_gstin: null, doc_number: null, doc_date: null, invoice_total: null, unclear: ["supplier_gstin"] }) });
    server.reply(`${B}/products`, { status: 200, body: { items: [], has_more: false } });
    open("/b/b-1/purchases/d-1");
    expect(await screen.findByText(/We couldn't read this one, so please type it in/)).toBeInTheDocument();
    expect(screen.getByLabelText("Supplier GSTIN")).toHaveValue("");
    expect(screen.getByLabelText("Quantity, line 1")).toHaveValue("");
    expect(screen.queryByLabelText("Quantity, line 2")).toBeNull();
  });

  it("a decided draft cannot be edited", async () => {
    server.reply(`${B}/purchase-drafts/d-1`, { status: 200, body: draft({ decision: "confirmed" }) });
    server.reply(`${B}/products`, { status: 200, body: { items: [], has_more: false } });
    open("/b/b-1/purchases/d-1");
    expect(await screen.findByText(/This invoice was confirmed/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Confirm and add/ })).toBeNull();
  });
});

describe("review helpers", () => {
  it("reads the reader's date format and leaves anything else blank", () => {
    expect(isoDate("03-07-2026")).toBe("2026-07-03");
    expect(isoDate("2026-07-03")).toBe("");
    expect(isoDate(null)).toBe("");
  });

  it("sends a blank tax column as zero and never works an amount out", () => {
    const { head, lines } = startingState(draft() as never);
    const body = confirmBody(head, lines);
    expect(body.lines[0].igst).toBe("0");
    expect(body.lines[0].cess).toBe("0");
    expect(body.lines[0].taxable_value).toBe("200.00");
  });
});
