import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { blankForm, draftIn, formOf, newLine } from "../../src/screens/invoices/draftForm";
import { fakeApi } from "./fakeApi";

vi.mock("../../src/features", () => ({ FEATURES: { invoicing: true } })); // R1 ships with it off

const REFRESH = "/api/v1/auth/refresh";
const ME = "/api/v1/me/businesses";
const STATES = "/api/v1/refdata/state-codes";
const DRAFTS = "/api/v1/b/b-1/drafts";
const ONE = `${DRAFTS}/d-1`;
const mine = (role: string) => ({ status: 200, body: { businesses: [{ business_id: "b-1", display_name: "Vashi Essentials", gstin: null, role }] } });
const states = { status: 200, body: { on: "2026-11-09", states: [{ code: "19", name: "West Bengal" }, { code: "27", name: "Maharashtra" }] } };

const computation = (over: Record<string, unknown> = {}) => ({
  computed_pos: "19", pos_state_code: "19", is_inter_state: false, supply_class: "B2B", lines: [], gross_total: "1000.00", line_discount_total: "0.00",
  invoice_discount: "0.00", charges_total: "0.00", taxable_total: "1000.00", cgst_total: "90.00", sgst_total: "90.00", utgst: false, igst_total: "0.00",
  round_off: "0.00", doc_total: "1180.00", amount_in_words: "Rupees One Thousand One Hundred Eighty only", rounding_mode: "nearest_rupee", method_version: "1",
  blocks: [], warnings: [], ...over,
}); // fmt: skip
const draft = (over: Record<string, unknown> = {}) => ({
  id: "d-1", kind: "invoice", version: 1, customer_id: "c-1", cash_buyer: null, bill_to: { name: "Sharma Traders" }, ship_to: null, doc_date: null,
  invoice_discount: "0.00", charges: [], eway: null, customer_collects: false, ship_to_third_party: false, pos_override: null, pos_override_reason: null,
  lines: [{ id: "l-1", line_no: 1, product_id: "p-1", quantity: "10", unit_price: "100.00", discount_kind: null, discount_value: null }],
  total: "1180.00", ready: true, computed_at: "2026-11-09T10:00:00Z", created_at: "2026-11-09T10:00:00Z", updated_at: "2026-11-09T10:00:00Z", computation: null, ...over,
}); // fmt: skip
const product = { id: "p-1", name: "Aloe Vera Gel 200 ml", hsn: "3304", code: "AVG", sale_rate: "120.00", status: "active", version: 1, warnings: [] };
const customer = { id: "c-1", name: "Sharma Traders", gstin: "19AAAAA0000A1Z5", status: "active", version: 1, warnings: [] };

let server: ReturnType<typeof fakeApi>;
beforeEach(() => {
  resetSessionForTests();
  server = fakeApi();
  server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
  server.reply(ME, mine("owner"));
  server.reply(STATES, states);
});
afterEach(() => vi.unstubAllGlobals());

const open = (path: string) => {
  window.history.replaceState(null, "", path);
  render(<App />);
};
const sent = (path: string, method: string) => server.sent.filter((s) => s.path === path && s.method === method);

describe("the draft invoice form", () => {
  it("creates a draft once, with the picked customer and product, and shows the server's totals and checks", async () => {
    server.reply("/api/v1/b/b-1/customers", { status: 200, body: { items: [customer], has_more: false } });
    server.reply("/api/v1/b/b-1/products", { status: 200, body: { items: [product], has_more: false } });
    server.reply("/api/v1/b/b-1/products/p-1", { status: 200, body: product });
    server.reply(DRAFTS, { status: 503 }, { status: 201, body: draft({ computation: computation({ blocks: [{ code: "hsn_short", fix: "Add a 6-digit HSN", field: "lines", line_no: 1 }], warnings: [{ code: "rate_unconfirmed", fix: "The rate isn't confirmed with your CA", field: null, line_no: null }] }) }) });
    open("/b/b-1/invoices/new");
    fireEvent.change(await screen.findByLabelText("Find a customer"), { target: { value: "sharma" } });
    fireEvent.click(await screen.findByRole("button", { name: /Sharma Traders · 19AAAAA0000A1Z5/ }, { timeout: 3000 }));
    fireEvent.change(screen.getByLabelText("Add a product"), { target: { value: "aloe" } });
    fireEvent.click(await screen.findByRole("button", { name: /Aloe Vera Gel 200 ml · HSN 3304/ }, { timeout: 3000 }));
    fireEvent.change(screen.getByLabelText("Quantity"), { target: { value: " 10 " } });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(await screen.findByText(/Something went wrong on our side/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(await screen.findByText("Line 1: Add a 6-digit HSN")).toBeInTheDocument();
    expect(screen.getByText("The rate isn't confirmed with your CA")).toBeInTheDocument();
    expect(screen.getByText("₹1,180.00")).toBeInTheDocument();
    const [first, second] = sent(DRAFTS, "POST");
    expect(second.headers.get("Idempotency-Key")).toBe(first.headers.get("Idempotency-Key"));
    expect(second.body).toMatchObject({ kind: "invoice", customer_id: "c-1", cash_buyer: null, ship_to: null, lines: [{ product_id: "p-1", quantity: "10", unit_price: null, discount_kind: null }] });
    expect(await screen.findByRole("heading", { name: "Draft invoice" })).toBeInTheDocument();
  });

  it("saves a change with the version it opened, and offers their version on a stale save", async () => {
    // GET, then the save (409), then the re-read: the fake answers per path, in order.
    server.reply(
      ONE,
      { status: 200, body: draft() },
      { status: 409, body: { error: { code: "stale_record", message: "stale" } } },
      { status: 200, body: draft({ version: 3, invoice_discount: "5.00" }) },
    );
    server.reply("/api/v1/b/b-1/products/p-1", { status: 200, body: product });
    open("/b/b-1/invoices/d-1");
    expect(await screen.findByText("Sharma Traders")).toBeInTheDocument();
    expect(screen.getByText(/Total as last saved:/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Quantity"), { target: { value: "12" } });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(await screen.findByText(/Someone saved this draft after you opened it/)).toBeInTheDocument();
    expect(sent(ONE, "PUT")[0].headers.get("If-Match")).toBe("1");
    fireEvent.click(screen.getByRole("button", { name: "Load their version" }));
    expect(await screen.findByDisplayValue("5.00")).toBeInTheDocument();
    expect(screen.queryByText(/Someone saved this draft/)).toBeNull();
  });

  it("previews only the saved draft, and links the PDF once it is ready", async () => {
    server.reply(ONE, { status: 200, body: draft() });
    server.reply("/api/v1/b/b-1/products/p-1", { status: 200, body: product });
    server.reply(`${ONE}/preview`, { status: 202, body: { job_id: "j-1", draft_version: 1 } });
    server.reply(`${ONE}/preview/j-1`, { status: 200, body: { status: "ready", url: "https://files.example/p.pdf" } });
    open("/b/b-1/invoices/d-1");
    await screen.findByText("Sharma Traders");
    fireEvent.change(screen.getByLabelText("Quantity"), { target: { value: "11" } });
    expect(screen.getByRole("button", { name: "Preview PDF" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Quantity"), { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: "Preview PDF" }));
    const link = await screen.findByRole("link", { name: "Open the preview (PDF)" });
    expect(link).toHaveAttribute("href", "https://files.example/p.pdf");
    expect(screen.getByText("Draft, not a tax invoice.")).toBeInTheDocument();
  });

  it("after a save, a customer draft whose server-filled ship-to is the customer's own address is not dirty", async () => {
    const filled = { line1: "12 MG Road", line2: null, city: "Kolkata", pin: "700001", state_code: "19" }; // no "name": the server's copy
    server.reply(ONE, { status: 200, body: draft({ ship_to: filled, computation: computation() }) });
    server.reply("/api/v1/b/b-1/products/p-1", { status: 200, body: product });
    server.reply(`${ONE}/preview`, { status: 202, body: { job_id: "j-1", draft_version: 1 } });
    server.reply(`${ONE}/preview/j-1`, { status: 200, body: { status: "queued" } });
    open("/b/b-1/invoices/d-1");
    await screen.findByText("Sharma Traders");
    expect(screen.getByLabelText("Ship to a different address")).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Save draft" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Preview PDF" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Preview PDF" }));
    expect(await screen.findByText("Preparing the preview…")).toBeInTheDocument();
  });

  it("opens an address the user entered as a different ship-to, with its third-party flag", async () => {
    const own = { name: "Depot", line1: "9 Dock Rd", line2: null, city: "Pune", pin: "411001", state_code: "27" };
    server.reply(ONE, { status: 200, body: draft({ ship_to: own, ship_to_third_party: true }) });
    server.reply("/api/v1/b/b-1/products/p-1", { status: 200, body: product });
    open("/b/b-1/invoices/d-1");
    await screen.findByText("Sharma Traders");
    expect(screen.getByLabelText("Ship to a different address")).toBeChecked();
    expect(screen.getByLabelText("Ship-to name")).toHaveValue("Depot");
    expect(screen.getByLabelText(/Goods go to a third party/)).toBeChecked();
  });

  it("offers no third-party box on a cash sale", async () => {
    open("/b/b-1/invoices/new");
    fireEvent.click(await screen.findByLabelText("Cash sale (no GSTIN)"));
    fireEvent.click(screen.getByLabelText("Ship to a different address"));
    expect(screen.queryByLabelText(/Goods go to a third party/)).toBeNull();
  });

  it("is not there for a role that can't create documents", async () => {
    server = fakeApi();
    server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
    server.reply(ME, mine("ca"));
    server.reply(STATES, states);
    open("/b/b-1/invoices/new");
    expect(await screen.findByRole("heading", { name: "We couldn't find that page" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Find a customer")).toBeNull();
  });
});

describe("the form's body", () => {
  it("sends a cash buyer without a customer, and no ship-to when the customer collects", () => {
    const f = { ...blankForm(), buyer: "cash" as const, customer_id: "c-1", cash_state: "27", cash_name: " ", ship_different: true, customer_collects: true, third_party: true };
    expect(draftIn({ ...f, lines: [{ ...newLine(), product_id: "p-1", quantity: " 2 ", discount_kind: "percent", discount_value: "5" }] })).toMatchObject({
      customer_id: null,
      cash_buyer: { state_code: "27", name: null, address: null },
      ship_to: null,
      ship_to_third_party: false,
      customer_collects: true,
      lines: [{ product_id: "p-1", quantity: "2", unit_price: null, discount_kind: "percent", discount_value: "5" }],
    });
  });

  it("drops a ticked third-party flag when the buyer becomes a cash sale", () => {
    const f = { ...blankForm(), buyer: "cash" as const, cash_state: "27", ship_different: true, third_party: true, ship: { ...blankForm().ship, state_code: "27" } };
    expect(draftIn(f)).toMatchObject({ ship_to_third_party: false });
  });

  it("sends the place-of-supply reason only with an override, and reopens a saved draft as the form it was", () => {
    expect(draftIn({ ...blankForm(), pos_reason: "stray" })).toMatchObject({ pos_override: null, pos_override_reason: null });
    const f = formOf(draft({ pos_override: "27", pos_override_reason: "Delivered in Pune" }) as never, { "p-1": "Gel" });
    expect(f).toMatchObject({ buyer: "customer", customer_name: "Sharma Traders", pos_override: "27", pos_reason: "Delivered in Pune" });
    expect(f.lines[0]).toMatchObject({ key: "l-1", name: "Gel", quantity: "10", unit_price: "100.00" });
  });
});
