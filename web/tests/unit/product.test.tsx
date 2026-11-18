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
    expect(await screen.findByRole("button", { name: "Archive Neem soap" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete Neem soap" })).toBeInTheDocument();

    const [first, second] = sent(LIST, "POST");
    expect(second.headers.get("Idempotency-Key")).toBe(first.headers.get("Idempotency-Key"));
    expect(first.body).toEqual({
      code: "SOAP-1",
      name: "Neem soap",
      hsn: "3401",
      uqc: "NOS",
      sale_rate: "45",
      barcode: null,
      tax_category: "taxable",
      has_cess: false,
      rate: { rate: "18", valid_from: todayIst() },
    });
    expect(new URL(server.sent.find((s) => s.path === RATES)!.url).searchParams.get("on")).toBe(todayIst());
  });

  it("drops the chosen rate when it isn't in force on the new date", async () => {
    open("/b/b-1/products/new");
    await screen.findByRole("option", { name: "Numbers (NOS)" });
    server.reply(RATES, { status: 200, body: { on: todayIst(), rates: ["5", "18", "28"] } }, { status: 200, body: { on: "2026-03-01", rates: ["5", "18", "40"] } });
    fireEvent.click(screen.getByRole("radio", { name: "Taxable" }));
    await screen.findByRole("option", { name: "28%" });
    type("GST rate", "28");
    expect(screen.getByLabelText("GST rate")).toHaveValue("28");
    type("Rate applies from", "2026-03-01");
    await screen.findByRole("option", { name: "40%" });
    expect(screen.getByLabelText("GST rate")).toHaveValue("");
    // Nothing is chosen any more: the form says so in plain words and sends nothing.
    fireEvent.click(screen.getByRole("button", { name: "Add product" }));
    expect(await screen.findByText("Choose a GST rate.")).toBeInTheDocument();
    expect(sent(LIST, "POST")).toHaveLength(0);
    type("GST rate", "5");
    expect(screen.queryByText("Choose a GST rate.")).toBeNull();
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
  it("keeps only digits and one decimal point, up to 2 decimals, in the sale rate", async () => {
    open("/b/b-1/products/new");
    await screen.findByRole("option", { name: "Numbers (NOS)" });
    const box = screen.getByLabelText("Sale rate per unit, excluding GST (₹)");
    type("Sale rate per unit, excluding GST (₹)", "Rs 1,20a.505.9");
    expect(box).toHaveValue("120.50");
    type("Sale rate per unit, excluding GST (₹)", "-4e5");
    expect(box).toHaveValue("45");
    type("Sale rate per unit, excluding GST (₹)", "abc");
    expect(box).toHaveValue("");
  });

  it("hides the date a rate starts under Advanced, today by default, and opens it when the server names it", async () => {
    open("/b/b-1/products/new");
    await screen.findByRole("option", { name: "Numbers (NOS)" });
    server.reply(RATES, { status: 200, body: { on: todayIst(), rates: ["5", "18"] } });
    fireEvent.click(screen.getByRole("radio", { name: "Taxable" }));
    await screen.findByRole("option", { name: "18%" });
    expect(screen.getByLabelText("Rate applies from")).not.toBeVisible();
    expect(screen.getByLabelText("Rate applies from")).toHaveValue(todayIst());
    const advanced = screen.getByRole("button", { name: "Advanced" });
    expect(advanced).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(advanced);
    expect(screen.getByLabelText("Rate applies from")).toBeVisible();
    fireEvent.click(advanced);
    expect(screen.getByLabelText("Rate applies from")).not.toBeVisible();
    type("GST rate", "18");
    server.reply(LIST, { status: 422, body: { error: { code: "invalid", message: "Pick a later date", field: "rate.valid_from" } } });
    fireEvent.click(screen.getByRole("button", { name: "Add product" }));
    await screen.findByText("Pick a later date");
    expect(screen.getByLabelText("Rate applies from")).toBeVisible();
  });

  it("says why the rate list is empty, and does not leave a blank dropdown", async () => {
    open("/b/b-1/products/new");
    await screen.findByRole("option", { name: "Numbers (NOS)" });
    server.reply(RATES, { status: 200, body: { on: "2017-01-01", rates: [] } });
    fireEvent.click(screen.getByRole("radio", { name: "Taxable" }));
    expect(screen.getByLabelText("GST rate")).toBeDisabled();
    expect(screen.getByRole("option", { name: "Loading rates…" })).toBeInTheDocument();
    expect(await screen.findByText(/No GST rates are on file for that date/)).toBeInTheDocument();
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
    await screen.findByText(/Saved\./);
    const patches = sent(ONE, "PATCH");
    expect(patches[1].headers.get("If-Match")).toBe("4");
    expect(patches[1].body).toEqual({ name: "Neem bath soap" });
  });

  it("won't archive while there are unsaved edits", async () => {
    server.reply(ONE, { status: 200, body: detail() });
    open("/b/b-1/products/p-1");
    await screen.findByRole("heading", { name: "Neem soap" });
    expect(screen.getByRole("button", { name: "Archive" })).toBeEnabled();
    type("Name", "Neem bath soap");
    expect(screen.getByRole("button", { name: "Archive" })).toBeDisabled();
    expect(screen.getByText("Save or undo your changes first.")).toBeInTheDocument();
    type("Name", "Neem soap");
    expect(screen.getByRole("button", { name: "Archive" })).toBeEnabled();
  });

  it("offers Delete only for a product never used, and asks first", async () => {
    server.reply(`GET ${ONE}`, { status: 200, body: detail() });
    server.reply(`DELETE ${ONE}`, { status: 204 });
    server.reply(LIST, { status: 200, body: { items: [], has_more: false } });
    open("/b/b-1/products/p-1");
    await screen.findByRole("heading", { name: "Neem soap" });
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    fireEvent.click(screen.getByRole("button", { name: "Yes, delete" }));
    await screen.findByRole("heading", { name: "Products" });
    expect(sent(ONE, "DELETE")[0].headers.get("If-Match")).toBe("3");
  });

  it("explains Archive and Delete separately, and Keep it cancels either question", async () => {
    server.reply(ONE, { status: 200, body: detail() });
    open("/b/b-1/products/p-1");
    await screen.findByRole("heading", { name: "Neem soap" });
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
    const v = { code: "A", name: "N", hsn: "3401", uqc: "NOS", sale_rate: "1.00", barcode: "", tax_category: "taxable" as const, has_cess: false };
    expect(changedFields(v, { ...v })).toEqual({});
    expect(changedFields(v, { ...v, name: " N " })).toEqual({});
    expect(changedFields(v, { ...v, barcode: "890", has_cess: true })).toEqual({ barcode: "890", has_cess: true });
  });

  it("rebases the user's edits onto a newer version", () => {
    const v = { code: "A", name: "N", hsn: "3401", uqc: "NOS", sale_rate: "1.00", barcode: "", tax_category: "taxable" as const, has_cess: false };
    expect(rebase(v, { ...v, sale_rate: "2.00" }, { ...v, name: "M" })).toEqual({ ...v, name: "M", sale_rate: "2.00" });
    expect(rebase(v, { ...v, name: "Theirs" }, { ...v, name: "Mine" })).toEqual({ ...v, name: "Mine" });
  });

  it("maps validation paths for the nested rate", () => {
    expect(formField("rate.valid_from")).toBe("valid_from");
    expect(formField("code")).toBe("code");
    expect(formField(undefined)).toBeUndefined();
  });
});
