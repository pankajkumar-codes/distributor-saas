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
  it("is created once per form, with its first GST rate, and opens its own page", async () => {
    open("/b/b-1/products/new");
    await screen.findByRole("option", { name: "Numbers (NOS)" });
    server.reply(LIST, { status: 503 }, { status: 201, body: detail({ version: 1 }) });
    server.reply(ONE, { status: 200, body: detail({ version: 1 }) });
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
    expect(await screen.findByRole("heading", { name: "Neem soap" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/b/b-1/products/p-1");

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
    server.reply(LIST, { status: 422, body: { error: { code: "invalid", message: "Choose a rate", field: "rate.rate" } } });
    fireEvent.click(screen.getByRole("button", { name: "Add product" }));
    await screen.findByText("Choose a rate");
    expect(sent(LIST, "POST")[0].body).toMatchObject({ rate: { rate: "", valid_from: "2026-03-01" } });
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

describe("editing a product", () => {
  it("sends only what changed, with the version it was opened at", async () => {
    server.reply(ONE, { status: 200, body: detail() });
    open("/b/b-1/products/p-1");
    await screen.findByRole("heading", { name: "Neem soap" });
    server.reply(ONE, { status: 200, body: detail({ name: "Neem bath soap", version: 4 }) });
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
      ONE,
      { status: 409, body: { error: { code: "stale_record", message: "Someone changed this product since you opened it" } } },
      { status: 200, body: detail({ sale_rate: "50.00", version: 4 }) },
      { status: 200, body: detail({ sale_rate: "48.00", version: 5 }) },
    );
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
      ONE,
      { status: 409, body: { error: { code: "stale_record", message: "Someone changed this product since you opened it" } } },
      { status: 200, body: detail({ sale_rate: "50.00", version: 4 }) },
      { status: 200, body: detail({ name: "Neem bath soap", sale_rate: "50.00", version: 5 }) },
    );
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
    server.reply(ONE, { status: 200, body: detail() }, { status: 204 });
    server.reply(LIST, { status: 200, body: { items: [], has_more: false } });
    open("/b/b-1/products/p-1");
    await screen.findByRole("heading", { name: "Neem soap" });
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    fireEvent.click(screen.getByRole("button", { name: "Yes, delete" }));
    await screen.findByRole("heading", { name: "Products" });
    expect(sent(ONE, "DELETE")[0].headers.get("If-Match")).toBe("3");
  });

  it("only archives a product that is on invoices", async () => {
    server.reply(ONE, { status: 200, body: detail({ in_use: true }) });
    server.reply(`${ONE}/archive`, { status: 200, body: detail({ in_use: true, status: "archived", version: 4 }) });
    open("/b/b-1/products/p-1");
    await screen.findByRole("heading", { name: "Neem soap" });
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Archive" }));
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
