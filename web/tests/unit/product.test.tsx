import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { todayIst } from "../../src/format/dates";
import { changedFields, formField, rebase } from "../../src/screens/products/ProductPage";
import { fakeApi } from "./fakeApi";

const REFRESH = "/api/v1/auth/refresh";
const ME = "/api/v1/me/businesses";
const UNITS = "/api/v1/b/b-1/units";
const RATES = "/api/v1/refdata/gst-rates";
const LIST = "/api/v1/b/b-1/products";
const ONE = "/api/v1/b/b-1/products/p-1";
const me = { status: 200, body: { businesses: [{ business_id: "b-1", display_name: "Vashi Essentials", gstin: null, role: "owner" }] } };
const units = { status: 200, body: [{ code: "NOS", name: "Numbers" }, { code: "KGS", name: "Kilograms" }] };

const detail = (over: Record<string, unknown> = {}) => ({
  id: "p-1",
  code: "SOAP-1",
  name: "Neem soap",
  hsn: "3401",
  uqc: "NOS",
  sale_rate: "45.00",
  barcode: null,
  tax_category: "taxable",
  has_cess: false,
  status: "active",
  version: 3,
  in_use: false,
  rate_on: { rate: "18", rate_id: "r-1", valid_from: "2025-09-22", confirmed: false },
  warnings: [],
  rate_changed_within_warning_window: false,
  rates: [],
  ...over,
});

let server: ReturnType<typeof fakeApi>;

beforeEach(() => {
  resetSessionForTests();
  server = fakeApi();
  server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
  server.reply(ME, me);
  server.reply(UNITS, units);
});
afterEach(() => vi.unstubAllGlobals());

function open(path: string) {
  window.history.replaceState(null, "", path);
  render(<App />);
}
const type = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
const sent = (path: string, method: string) => server.sent.filter((s) => s.path === path && s.method === method);

/** The product page keeps Rate history and Archive or delete on tabs (mocks v16 one-screen rule). */
const tab = (name: string) => fireEvent.click(screen.getByRole("tab", { name }));

describe("a new product", () => {
  it("is created once per form, with its first GST rate, and lands on the list", async () => {
    open("/b/b-1/products/new");
    await screen.findByRole("option", { name: "Numbers (NOS)" });
    server.reply(LIST, { status: 503 }, { status: 201, body: detail({ version: 1 }) });
    server.reply(`GET ${LIST}`, { status: 200, body: { items: [detail({ version: 1 })], has_more: false } });
    type("Product code", " SOAP-1 ");
    type("Name", "Neem soap");
    type("HSN (optional)", "3401");
    type("Unit", "NOS");
    type("Sale rate per unit, excluding GST (₹)", "45");
    type("MRP, incl. GST (₹, optional)", " 52.50 ");
    server.reply(RATES, { status: 200, body: { on: todayIst(), rates: ["0.25", "3", "5", "12", "18", "28"] } });
    fireEvent.click(screen.getByRole("radio", { name: "Taxable" }));
    await screen.findByRole("option", { name: "18%" });
    type("GST rate", "18");
    fireEvent.click(screen.getByRole("button", { name: "Add product" }));
    expect(await screen.findByText(/Something went wrong on our side/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Add product" }));
    expect(await screen.findByRole("heading", { name: "Products" })).toBeInTheDocument(); // lands on the list
    expect(window.location.pathname).toBe("/b/b-1/products");
    expect(screen.getByText("Added Neem soap.")).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "Neem soap" })).toHaveAttribute("href", "/b/b-1/products/p-1"); // archive and delete are on its page

    const [first, second] = sent(LIST, "POST");
    expect(second.headers.get("Idempotency-Key")).toBe(first.headers.get("Idempotency-Key"));
    expect(first.body).toEqual({
      code: "SOAP-1",
      name: "Neem soap",
      hsn: "3401",
      uqc: "NOS",
      sale_rate: "45",
      mrp: "52.50",
      barcode: null,
      tax_category: "taxable",
      has_cess: false,
      rate: { rate: "18", valid_from: todayIst() },
    });
    expect(new URL(server.sent.find((s) => s.path === RATES)!.url).searchParams.get("on")).toBe(todayIst());
  });

  it("starts a fresh key when the server says the key belonged to a different request", async () => {
    open("/b/b-1/products/new");
    await screen.findByRole("option", { name: "Numbers (NOS)" });
    const mismatch = { status: 409, body: { error: { code: "idempotency_mismatch", message: "This Idempotency-Key was already used for a different request" } } };
    server.reply(LIST, mismatch, { status: 201, body: detail({ version: 1 }) });
    server.reply(`GET ${LIST}`, { status: 200, body: { items: [detail({ version: 1 })], has_more: false } });
    type("Product code", "SOAP-1");
    type("Name", "Neem soap");
    type("Unit", "NOS");
    type("Sale rate per unit, excluding GST (₹)", "45");
    server.reply(RATES, { status: 200, body: { on: todayIst(), rates: ["18"] } });
    fireEvent.click(screen.getByRole("radio", { name: "Taxable" }));
    await screen.findByRole("option", { name: "18%" });
    type("GST rate", "18");
    fireEvent.click(screen.getByRole("button", { name: "Add product" }));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Add product" }));
    expect(await screen.findByText("Added Neem soap.")).toBeInTheDocument();
    const [first, second] = sent(LIST, "POST");
    expect(second.headers.get("Idempotency-Key")).not.toBe(first.headers.get("Idempotency-Key"));
  });

  it("never shows the server's pattern text under the GST rate", async () => {
    open("/b/b-1/products/new");
    await screen.findByRole("option", { name: "Numbers (NOS)" });
    server.reply(RATES, { status: 200, body: { on: todayIst(), rates: ["5", "18"] } });
    fireEvent.click(screen.getByRole("radio", { name: "Taxable" }));
    await screen.findByRole("option", { name: "18%" });
    type("GST rate", "18");
    server.reply(LIST, { status: 422, body: { error: { code: "invalid", message: "String should match pattern '^\\s*[0-9]+$'", field: "rate.rate" } } });
    fireEvent.click(screen.getByRole("button", { name: "Add product" }));
    expect(await screen.findByText("Choose a GST rate.")).toBeInTheDocument();
    expect(screen.queryByText(/should match pattern/)).toBeNull();
  });

  it("sends no rate for an exempt product, and shows the server's words under the field it names", async () => {
    open("/b/b-1/products/new");
    await screen.findByRole("option", { name: "Numbers (NOS)" });
    server.reply(LIST, { status: 422, body: { error: { code: "code_taken", message: "Another product already uses this code", field: "code" } } });
    type("Product code", "SOAP-1");
    fireEvent.click(screen.getByRole("radio", { name: "Exempt" }));
    expect(screen.queryByLabelText("GST rate")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Add product" }));
    expect(await screen.findByText("Another product already uses this code")).toBeInTheDocument();
    expect(screen.getByLabelText("Product code")).toHaveAttribute("aria-invalid", "true");
    expect(sent(LIST, "POST")[0].body).toMatchObject({ tax_category: "exempt", rate: null });
  });
});

describe("the new product form's lists and fields", () => {
  it("keeps what was typed in the sale rate and says what is wrong, so a price never changes silently", async () => {
    open("/b/b-1/products/new");
    await screen.findByRole("option", { name: "Numbers (NOS)" });
    const label = "Sale rate per unit, excluding GST (₹)";
    const box = screen.getByLabelText(label);
    const cases: [string, string | null][] = [
      ["10.999", "Use at most 2 decimal places."],
      ["-10", "A price can't be negative."],
      ["1,200", "Enter a number, like 45 or 45.50."],
      ["Rs 120", "Enter a number, like 45 or 45.50."],
      ["1.2.3", "Enter a number, like 45 or 45.50."],
      ["12345678901234567", "That number is too large."],
      ["10.", null], // still typing
      ["45.50", null],
    ];
    for (const [text, message] of cases) {
      type(label, text);
      expect(box).toHaveValue(text); // nothing dropped
      if (message) expect(await screen.findByText(message)).toBeInTheDocument();
      else expect(screen.queryByRole("alert")).toBeNull();
    }
  });

  it("does not save a sale rate with a problem, and sends a good one exactly as typed", async () => {
    open("/b/b-1/products/new");
    await screen.findByRole("option", { name: "Numbers (NOS)" });
    type("Product code", "G1");
    type("Name", "Gel");
    type("Unit", "NOS");
    type("Sale rate per unit, excluding GST (₹)", "10.999");
    fireEvent.click(screen.getByRole("button", { name: /add product/i }));
    expect(await screen.findByText("Use at most 2 decimal places.")).toBeInTheDocument();
    expect(server.sent.some((s) => s.method === "POST" && s.path.endsWith("/products"))).toBe(false);
    type("Sale rate per unit, excluding GST (₹)", "10.");
    fireEvent.click(screen.getByRole("button", { name: /add product/i }));
    expect(await screen.findByText("Enter a number, like 45 or 45.50.")).toBeInTheDocument();
    expect(server.sent.some((s) => s.method === "POST" && s.path.endsWith("/products"))).toBe(false);
  });

  it("has no Advanced link or start date: the first rate starts today, and a date error shows under the rate (#388)", async () => {
    open("/b/b-1/products/new");
    await screen.findByRole("option", { name: "Numbers (NOS)" });
    server.reply(RATES, { status: 200, body: { on: todayIst(), rates: ["5", "18"] } });
    fireEvent.click(screen.getByRole("radio", { name: "Taxable" }));
    await screen.findByRole("option", { name: "18%" });
    expect(screen.queryByRole("button", { name: "Advanced" })).toBeNull();
    expect(screen.queryByLabelText("Rate applies from")).toBeNull();
    type("Product code", "SOAP-1");
    type("Name", "Neem soap");
    type("Unit", "NOS");
    type("Sale rate per unit, excluding GST (₹)", "45");
    type("GST rate", "18");
    server.reply(LIST, { status: 422, body: { error: { code: "invalid", message: "Pick a later date", field: "rate.valid_from" } } });
    fireEvent.click(screen.getByRole("button", { name: "Add product" }));
    expect(await screen.findByText("Pick a later date")).toBeInTheDocument();
    const [post] = sent(LIST, "POST");
    expect((post.body as unknown as { rate: unknown }).rate).toEqual({ rate: "18", valid_from: todayIst() });
  });

  it("says why the rate list is empty, and does not leave a blank dropdown", async () => {
    open("/b/b-1/products/new");
    await screen.findByRole("option", { name: "Numbers (NOS)" });
    server.reply(RATES, { status: 200, body: { on: "2017-01-01", rates: [] } });
    fireEvent.click(screen.getByRole("radio", { name: "Taxable" }));
    expect(screen.getByLabelText("GST rate")).toBeDisabled();
    expect(screen.getByRole("option", { name: "Loading rates…" })).toBeInTheDocument();
    expect(await screen.findByText(/No GST rates are on file for today/)).toBeInTheDocument();
    expect(screen.getByLabelText("GST rate")).toBeDisabled();
  });

  it("shows an error with Try again when the units cannot be loaded", { timeout: 15000 }, async () => {
    server = fakeApi(); // without the units the other tests start with
    server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
    server.reply(ME, me);
    server.reply(UNITS, { status: 500 }, { status: 500 }, { status: 500 });
    open("/b/b-1/products/new");
    expect(await screen.findByText(/We couldn't load the list of units/, undefined, { timeout: 8000 })).toBeInTheDocument();
    server.reply(UNITS, { status: 200, body: units.body });
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("option", { name: "Numbers (NOS)" })).toBeInTheDocument();
  });

  it("shows an error with Try again when the GST rates cannot be loaded", { timeout: 15000 }, async () => {
    open("/b/b-1/products/new");
    await screen.findByRole("option", { name: "Numbers (NOS)" });
    server.reply(RATES, { status: 503 }, { status: 503 }, { status: 503 });
    fireEvent.click(screen.getByRole("radio", { name: "Taxable" }));
    expect(await screen.findByText(/We couldn't load the GST rates/, undefined, { timeout: 8000 })).toBeInTheDocument();
    expect(screen.getByLabelText("GST rate")).toBeDisabled();
    server.reply(RATES, { status: 200, body: { on: todayIst(), rates: ["18"] } });
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("option", { name: "18%" })).toBeInTheDocument();
  });
});

describe("editing a product", () => {
  it("sends only what changed, with the version it was opened at", async () => {
    server.reply(ONE, { status: 200, body: detail() });
    open("/b/b-1/products/p-1");
    await screen.findByRole("heading", { name: "Neem soap" });
    server.reply(`PATCH ${ONE}`, { status: 200, body: detail({ name: "Neem bath soap", version: 4 }) });
    type("Name", "Neem bath soap");
    type("HSN (optional)", " ");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText(/Saved\. Invoices already finalized keep/)).toBeInTheDocument();
    const [patch] = sent(ONE, "PATCH");
    expect(patch.body).toEqual({ name: "Neem bath soap", hsn: null });
    expect(patch.headers.get("If-Match")).toBe("3");
  });

  it("asks for a GST rate when an exempt product is changed to Taxable, and sends it with the edit", async () => {
    const exempt = detail({ tax_category: "exempt", rate_on: null, rates: [] });
    server.reply(ONE, { status: 200, body: exempt });
    open("/b/b-1/products/p-1");
    await screen.findByRole("heading", { name: "Neem soap" });
    expect(screen.queryByLabelText("GST rate")).not.toBeInTheDocument();
    server.reply(RATES, { status: 200, body: { on: todayIst(), rates: ["0.25", "3", "5", "18", "40"] } });
    fireEvent.click(screen.getByRole("radio", { name: "Taxable" }));
    await screen.findByRole("option", { name: "18%" });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("Choose a GST rate.")).toBeInTheDocument();
    expect(sent(ONE, "PATCH")).toHaveLength(0);
    server.reply(`PATCH ${ONE}`, { status: 200, body: detail({ version: 4 }) });
    type("GST rate", "18");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText(/Saved\. Invoices already finalized keep/)).toBeInTheDocument();
    const [patch] = sent(ONE, "PATCH");
    expect(patch.body).toEqual({ tax_category: "taxable", rate: { rate: "18", valid_from: todayIst() } });
    expect(screen.queryByLabelText("GST rate")).not.toBeInTheDocument(); // later rates go through the rate history
  });

  it("sends no rate when a taxable product is changed to Nil rated, and says its rates will be voided", async () => {
    server.reply(ONE, { status: 200, body: detail() });
    open("/b/b-1/products/p-1");
    await screen.findByRole("heading", { name: "Neem soap" });
    fireEvent.click(screen.getByRole("radio", { name: "Nil rated" }));
    expect(screen.getByText("Its GST rates will be voided. They stay in the rate history.")).toBeInTheDocument();
    expect(screen.queryByLabelText("GST rate")).not.toBeInTheDocument();
    server.reply(`PATCH ${ONE}`, { status: 200, body: detail({ tax_category: "nil_rated", rate_on: null, version: 4 }) });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText(/Saved\. Invoices already finalized keep/)).toBeInTheDocument();
    expect(sent(ONE, "PATCH")[0].body).toEqual({ tax_category: "nil_rated" });
  });

  it("says a product on invoices can't move between taxable and not taxable", async () => {
    server.reply(ONE, { status: 200, body: detail({ in_use: true }) });
    open("/b/b-1/products/p-1");
    await screen.findByRole("heading", { name: "Neem soap" });
    expect(screen.getByText("This product is on invoices, so it can't move between taxable and not taxable.")).toBeInTheDocument();
  });

  it("sends one request and shows Saved when Save is pressed twice quickly", async () => {
    server.reply(ONE, { status: 200, body: detail() });
    open("/b/b-1/products/p-1");
    await screen.findByRole("heading", { name: "Neem soap" });
    server.reply(`PATCH ${ONE}`, { status: 200, body: detail({ name: "Neem bath soap", version: 4 }) }, { status: 409, body: { error: { code: "stale_record", message: "changed" } } });
    type("Name", "Neem bath soap");
    const save = screen.getByRole("button", { name: "Save changes" });
    fireEvent.click(save);
    fireEvent.click(save);
    expect(await screen.findByText(/Saved\. Invoices already finalized keep/)).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 50));
    expect(sent(ONE, "PATCH")).toHaveLength(1);
    expect(screen.getByText(/Saved\. Invoices already finalized keep/)).toBeInTheDocument();
  });

  it("after someone else saved first, keeps the user's values beside theirs, then saves against their version", async () => {
    server.reply(ONE, { status: 200, body: detail() });
    open("/b/b-1/products/p-1");
    await screen.findByRole("heading", { name: "Neem soap" });
    server.reply(
      `PATCH ${ONE}`,
      { status: 409, body: { error: { code: "stale_record", message: "Someone changed this product since you opened it" } } },
      { status: 200, body: detail({ sale_rate: "48.00", version: 5 }) },
    );
    server.reply(`GET ${ONE}`, { status: 200, body: detail({ sale_rate: "50.00", version: 4 }) });
    type("Sale rate per unit, excluding GST (₹)", "48.00");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText(/Someone changed this product since you opened it/)).toBeInTheDocument();
    expect(await screen.findByText("Now saved as: 50.00")).toBeInTheDocument();
    expect(screen.getByLabelText("Sale rate per unit, excluding GST (₹)")).toHaveValue("48.00");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await screen.findByText(/Saved\./);
    const patches = sent(ONE, "PATCH");
    expect(patches[1].headers.get("If-Match")).toBe("4");
    expect(patches[1].body).toEqual({ sale_rate: "48.00" });
  });

  it("after a reload, sends only the user's own edit and keeps the other person's change to another field", async () => {
    server.reply(ONE, { status: 200, body: detail() });
    open("/b/b-1/products/p-1");
    await screen.findByRole("heading", { name: "Neem soap" });
    server.reply(
      `PATCH ${ONE}`,
      { status: 409, body: { error: { code: "stale_record", message: "Someone changed this product since you opened it" } } },
      { status: 200, body: detail({ name: "Neem bath soap", sale_rate: "50.00", version: 5 }) },
    );
    server.reply(`GET ${ONE}`, { status: 200, body: detail({ sale_rate: "50.00", version: 4 }) });
    type("Name", "Neem bath soap");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("Someone else changed this.")).toBeInTheDocument();
    expect(screen.getByLabelText("Sale rate per unit, excluding GST (₹)")).toHaveValue("50.00");
    expect(screen.getByLabelText("Name")).toHaveValue("Neem bath soap");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await screen.findByText(/Saved\./, undefined, { timeout: 3000 });
    const patches = sent(ONE, "PATCH");
    expect(patches[1].headers.get("If-Match")).toBe("4");
    expect(patches[1].body).toEqual({ name: "Neem bath soap" });
  });

  it("won't archive while there are unsaved edits", async () => {
    server.reply(ONE, { status: 200, body: detail() });
    open("/b/b-1/products/p-1");
    await screen.findByRole("heading", { name: "Neem soap" });
    tab("Archive or delete");
    expect(screen.getByRole("button", { name: "Archive" })).toBeEnabled();
    tab("Details");
    type("Name", "Neem bath soap");
    tab("Archive or delete");
    expect(screen.getByRole("button", { name: "Archive" })).toBeDisabled();
    expect(screen.getByText("Save or undo your changes first.")).toBeInTheDocument();
    tab("Details");
    type("Name", "Neem soap");
    tab("Archive or delete");
    expect(screen.getByRole("button", { name: "Archive" })).toBeEnabled();
  });

  it("offers Delete only for a product never used, and asks first", async () => {
    server.reply(`GET ${ONE}`, { status: 200, body: detail() });
    server.reply(`DELETE ${ONE}`, { status: 204 });
    server.reply(LIST, { status: 200, body: { items: [], has_more: false } });
    open("/b/b-1/products/p-1");
    await screen.findByRole("heading", { name: "Neem soap" });
    tab("Archive or delete");
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    fireEvent.click(screen.getByRole("button", { name: "Yes, delete" }));
    await screen.findByRole("heading", { name: "Products" });
    expect(sent(ONE, "DELETE")[0].headers.get("If-Match")).toBe("3");
  });

  it("explains Archive and Delete separately, and Keep it cancels either question", async () => {
    server.reply(ONE, { status: 200, body: detail() });
    open("/b/b-1/products/p-1");
    await screen.findByRole("heading", { name: "Neem soap" });
    tab("Archive or delete");
    expect(screen.getByText(/Invoices already made keep it/)).toBeInTheDocument();
    expect(screen.getByText(/never been on an invoice/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    fireEvent.click(screen.getByRole("button", { name: "Keep it" }));
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Archive" }));
    fireEvent.click(screen.getByRole("button", { name: "Keep it active" }));
    expect(screen.getByRole("button", { name: "Archive" })).toBeInTheDocument();
    expect(sent(ONE, "DELETE")).toHaveLength(0);
  });

  it("only archives a product that is on invoices", async () => {
    server.reply(ONE, { status: 200, body: detail({ in_use: true }) });
    server.reply(`${ONE}/archive`, { status: 200, body: detail({ in_use: true, status: "archived", version: 4 }) });
    open("/b/b-1/products/p-1");
    await screen.findByRole("heading", { name: "Neem soap" });
    tab("Archive or delete");
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Archive" }));
    expect(sent(`${ONE}/archive`, "POST")).toHaveLength(0); // asks first
    fireEvent.click(screen.getByRole("button", { name: "Yes, archive" }));
    expect(await screen.findByText(/This product is archived/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Unarchive" })).toBeInTheDocument();
  });

  it("shows an error with Try again, not an empty form, when loading fails", async () => {
    server.reply(ONE, { status: 500 }, { status: 500 }, { status: 500 }, { status: 200, body: detail() });
    open("/b/b-1/products/p-1");
    expect(await screen.findByText(/We couldn't load this product/, {}, { timeout: 8000 })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save changes" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: "Neem soap" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save changes" })).toBeInTheDocument();
  }, 12000);

  it("is NotFound when the server doesn't know the product", async () => {
    server.reply(ONE, { status: 404, body: { error: { code: "not_found", message: "" } } });
    open("/b/b-1/products/p-1");
    expect(await screen.findByText(/couldn't find that page/i)).toBeInTheDocument();
  });
});

describe("helpers", () => {
  it("diffs the form against the opened version", () => {
    const v = { code: "A", name: "N", hsn: "3401", uqc: "NOS", sale_rate: "1.00", mrp: "", barcode: "", tax_category: "taxable" as const, has_cess: false };
    expect(changedFields(v, { ...v })).toEqual({});
    expect(changedFields(v, { ...v, name: " N " })).toEqual({});
    expect(changedFields(v, { ...v, barcode: "890", has_cess: true })).toEqual({ barcode: "890", has_cess: true });
    // MRP (#398): set as typed, and a cleared box sends null.
    expect(changedFields(v, { ...v, mrp: " 60.5 " })).toEqual({ mrp: "60.5" });
    expect(changedFields({ ...v, mrp: "60.50" }, { ...v, mrp: "" })).toEqual({ mrp: null });
  });

  it("rebases the user's edits onto a newer version", () => {
    const v = { code: "A", name: "N", hsn: "3401", uqc: "NOS", sale_rate: "1.00", mrp: "", barcode: "", tax_category: "taxable" as const, has_cess: false };
    expect(rebase(v, { ...v, sale_rate: "2.00" }, { ...v, name: "M" })).toEqual({ ...v, name: "M", sale_rate: "2.00" });
    expect(rebase(v, { ...v, name: "Theirs" }, { ...v, name: "Mine" })).toEqual({ ...v, name: "Mine" });
  });

  it("maps validation paths for the nested rate", () => {
    expect(formField("rate.valid_from")).toBe("valid_from");
    expect(formField("code")).toBe("code");
    expect(formField(undefined)).toBeUndefined();
  });
});
