import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { todayIst } from "../../src/format/dates";
import { fakeApi } from "./fakeApi";

// Roles without catalog.edit (CA, and support staff under a grant) see customers and products
// read-only: no create, save, archive, delete, rate or import actions. The server refuses them
// anyway; this keeps the screens from offering buttons that end in a 404 [Staff 2, #98].
const REFRESH = "/api/v1/auth/refresh";
const ME = "/api/v1/me/businesses";
const GRANTS = "/api/v1/support/grants";
const STATES = "/api/v1/refdata/state-codes";
const CUSTOMER = "/api/v1/b/b-1/customers/c-1";
const PRODUCTS = "/api/v1/b/b-1/products";
const PRODUCT = "/api/v1/b/b-1/products/p-1";
const as = (role: string) => ({ status: 200, body: { businesses: [{ business_id: "b-1", display_name: "Vashi Essentials", gstin: null, role }], is_support: false } });
const support = { status: 200, body: { businesses: [], is_support: true } };
const grants = { status: 200, body: { grants: [{ grant_id: "g-1", business_id: "b-1", business_name: "Vashi Essentials", expires_at: "2099-10-25T08:50:00Z" }] } };

const customer = {
  id: "c-1",
  name: "Sharma Traders",
  gstin: "19AAAAA0000A1Z5",
  gstin_state_code: "19",
  billing: { line1: "4 Park Street", line2: null, city: "Kolkata", pin: "700016", state_code: "19" },
  delivery_same_as_billing: true,
  delivery: null,
  credit_days: 30,
  status: "active",
  version: 3,
  in_use: false,
  warnings: [],
};
const product = {
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
  rates: [{ id: "r-1", rate: "18", valid_from: "2025-09-22", valid_until: null, voided: false, confirmation: null }],
};

let server: ReturnType<typeof fakeApi>;
beforeEach(() => {
  resetSessionForTests();
  server = fakeApi();
  server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
  server.reply(STATES, { status: 200, body: { on: "2026-11-02", states: [{ code: "19", name: "West Bengal" }] } });
  server.reply("/api/v1/b/b-1/units", { status: 200, body: [{ code: "NOS", name: "Numbers" }] });
  server.reply("/api/v1/refdata/gst-rates", { status: 200, body: { on: todayIst(), rates: ["5", "18"] } });
});
afterEach(() => vi.unstubAllGlobals());

function open(path: string) {
  window.history.replaceState(null, "", path);
  render(<App />);
}
const noButton = (name: string) => expect(screen.queryByRole("button", { name })).toBeNull();

describe("a read-only role", () => {
  it("sees a customer under support view with nothing to save, archive or delete", async () => {
    server.reply(ME, support);
    server.reply(GRANTS, grants);
    server.reply(CUSTOMER, { status: 200, body: customer });
    open("/b/b-1/customers/c-1");
    await screen.findByRole("heading", { name: "Sharma Traders" });
    expect(screen.getByLabelText("Name")).toBeDisabled();
    noButton("Save changes");
    noButton("Archive");
    noButton("Delete");
  });

  it.each(["/b/b-1/customers/new", "/b/b-1/products/new", "/b/b-1/products/import"])("gets not found on %s", async (path) => {
    server.reply(ME, as("ca"));
    open(path);
    expect(await screen.findByRole("heading", { name: "We couldn't find that page" })).toBeInTheDocument();
  });

  it("sees the product list without New product or Import", async () => {
    server.reply(ME, as("ca"));
    server.reply(PRODUCTS, { status: 200, body: { items: [], has_more: false } });
    open("/b/b-1/products");
    expect(await screen.findByText("No products yet.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "New product" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Import from a file" })).toBeNull();
  });

  it("sees a product and its rates with no edit, rate or archive actions", async () => {
    server.reply(ME, as("ca"));
    server.reply(PRODUCT, { status: 200, body: product });
    open("/b/b-1/products/p-1");
    await screen.findByRole("heading", { name: "Neem soap" });
    expect(screen.getByLabelText("Name")).toBeDisabled();
    noButton("Save changes");
    noButton("Void");
    noButton("Mark confirmed");
    noButton("Add rate");
    noButton("Archive");
  });

  it("still lets billing edit the catalog", async () => {
    server.reply(ME, as("billing"));
    server.reply(PRODUCT, { status: 200, body: product });
    open("/b/b-1/products/p-1");
    await screen.findByRole("heading", { name: "Neem soap" });
    expect(screen.getByRole("button", { name: "Save changes" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Void" })).toBeInTheDocument();
    noButton("Mark confirmed"); // owner and admin only (L3-3)
  });
});
