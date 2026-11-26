import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { todayIst } from "../../src/format/dates";
import { blankForm } from "../../src/screens/invoices/draftForm";
import { fakeApi } from "./fakeApi";

vi.mock("../../src/features", () => ({ FEATURES: { invoicing: true } }));
const demo = vi.hoisted(() => ({ on: false }));
vi.mock("../../src/demo", () => ({ isDemo: () => demo.on }));

const REFRESH = "/api/v1/auth/refresh";
const ME = "/api/v1/me/businesses";
const STATES = "/api/v1/refdata/state-codes";
const ONE = "/api/v1/b/b-1/drafts/d-1";
const states = { status: 200, body: { on: "2026-11-09", states: [{ code: "07", name: "Delhi" }, { code: "19", name: "West Bengal" }] } };
const address = (line1: string, city: string, pin: string, state_code: string) => ({ line1, line2: null, city, pin, state_code });
const delhi = {
  id: "c-1", name: "Demo Distributor Delhi", gstin: "07DEMOE3333E1ZU", gstin_state_code: "07", status: "active", version: 1, warnings: [], in_use: true, credit_days: 45,
  billing: address("9 Demo Chowk", "New Delhi", "110001", "07"), delivery_same_as_billing: false, delivery: address("3 Demo Godown Road", "Siliguri", "734001", "19"),
}; // fmt: skip
const howrah = { ...delhi, id: "c-2", name: "Howrah Stores", gstin: null, gstin_state_code: null, billing: address("7 Demo Para", "Howrah", "711101", "19"), delivery_same_as_billing: true, delivery: null };
const draft = {
  id: "d-1", kind: "invoice", version: 1, customer_id: "c-1", cash_buyer: null, bill_to: { name: "Demo Distributor Delhi" }, ship_to: null, doc_date: null,
  invoice_discount: "0.00", charges: [], eway: null, customer_collects: false, ship_to_third_party: false, pos_override: null, pos_override_reason: null, lines: [],
  total: "0.00", ready: false, computed_at: "2026-11-09T10:00:00Z", created_at: "2026-11-09T10:00:00Z", updated_at: "2026-11-09T10:00:00Z", computation: null,
}; // fmt: skip

let server: ReturnType<typeof fakeApi>;
beforeEach(() => {
  demo.on = false;
  resetSessionForTests();
  server = fakeApi();
  server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
  server.reply(ME, { status: 200, body: { businesses: [{ business_id: "b-1", display_name: "Demo Traders", gstin: null, role: "owner" }] } });
  server.reply(STATES, states);
});
afterEach(() => vi.unstubAllGlobals());

const open = (path: string) => {
  window.history.replaceState(null, "", path);
  render(<App />);
};

describe("the customer on a new invoice", () => {
  it("hides the search once a customer is picked, shows their GSTIN and addresses, and Change picks another", async () => {
    server.reply("/api/v1/b/b-1/customers", { status: 200, body: { items: [delhi], has_more: false } }, { status: 200, body: { items: [howrah], has_more: false } });
    open("/b/b-1/invoices/new");
    const box = await screen.findByLabelText("Find a customer");
    expect(server.paths()).not.toContain("/api/v1/b/b-1/customers"); // mocks v16: nothing suggested before a letter
    expect(box).toHaveAttribute("placeholder", "Find a customer: type a name or GSTIN");
    fireEvent.change(box, { target: { value: "delhi" } });
    fireEvent.click(await screen.findByRole("button", { name: /Demo Distributor Delhi.*07DEMOE3333E1ZU/ }, { timeout: 3000 }));

    const card = await screen.findByRole("region", { name: "Customer" });
    expect(card).toHaveTextContent("Demo Distributor Delhi");
    expect(card).toHaveTextContent("GSTIN 07DEMOE3333E1ZU");
    expect(card).toHaveTextContent("Bill to: 9 Demo Chowk, New Delhi, 110001, Delhi (07)");
    expect(card).toHaveTextContent("Ship to: 3 Demo Godown Road, Siliguri, 734001, West Bengal (19)");
    expect(screen.queryByLabelText("Find a customer")).toBeNull();
    // the picked customer came with its details, so nothing more was read
    expect(server.paths()).not.toContain("/api/v1/b/b-1/customers/c-1");

    fireEvent.click(screen.getByRole("button", { name: "Change" }));
    fireEvent.change(screen.getByLabelText("Find another customer"), { target: { value: "howrah" } });
    fireEvent.click(await screen.findByRole("button", { name: /^Howrah Stores/ }, { timeout: 3000 }));
    const again = await screen.findByRole("region", { name: "Customer" });
    expect(again).toHaveTextContent("Howrah Stores");
    expect(again).toHaveTextContent("No GSTIN (unregistered)");
    expect(again).not.toHaveTextContent("Ship to");
  });

  it("can back out of Change and keep the customer", async () => {
    server.reply(ONE, { status: 200, body: draft });
    server.reply("/api/v1/b/b-1/customers/c-1", { status: 200, body: delhi });
    open("/b/b-1/invoices/d-1");
    expect(await screen.findByText("GSTIN 07DEMOE3333E1ZU")).toBeInTheDocument(); // read once for a saved draft
    fireEvent.click(screen.getByRole("button", { name: "Change" }));
    // #427: "Keep <name>" sits under the search box, so the box keeps the field's full width.
    const search = screen.getByLabelText("Find another customer");
    const keep = screen.getByRole("button", { name: "Keep Demo Distributor Delhi" });
    expect(keep.parentElement).toHaveClass("pick-stack");
    expect(search.compareDocumentPosition(keep) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    fireEvent.click(keep);
    expect(screen.getByRole("region", { name: "Customer" })).toHaveTextContent("Demo Distributor Delhi");
    expect(screen.queryByLabelText("Find another customer")).toBeNull();
  });

  it("still shows the name when the customer's details can't be read", async () => {
    server.reply(ONE, { status: 200, body: draft });
    server.reply("/api/v1/b/b-1/customers/c-1", { status: 404, body: { error: { code: "not_found", message: "not found" } } });
    open("/b/b-1/invoices/d-1");
    expect(await screen.findByRole("region", { name: "Customer" })).toHaveTextContent("Demo Distributor Delhi");
  });
});

describe("adding a product that is already on the invoice (#427)", () => {
  const product = (id: string, code: string, name: string) => ({
    id, code, name, hsn: "330499", uqc: "NOS", sale_rate: "100.00", mrp: "118.00", barcode: null, tax_category: "taxable", has_cess: false, status: "active",
    version: 1, price_needed: false, in_use: true, rate_on: { rate: "18", rate_id: "r-1", valid_from: "2026-04-01", confirmed: true }, warnings: [],
  }); // fmt: skip
  const cream = product("p-1", "CREAM", "Face cream");
  const soap = product("p-2", "SOAP", "Neem soap");

  it("lists it greyed out with a note, and picking it adds nothing", async () => {
    server.reply(ONE, { status: 200, body: { ...draft, lines: [{ id: "l-1", line_no: 1, product_id: "p-1", quantity: "1", unit_price: "100.00", discount_kind: null, discount_value: null }] } });
    server.reply("/api/v1/b/b-1/customers/c-1", { status: 200, body: delhi });
    server.reply("/api/v1/b/b-1/products/p-1", { status: 200, body: cream });
    server.reply("/api/v1/b/b-1/products", { status: 200, body: { items: [cream, soap], has_more: false } });
    open("/b/b-1/invoices/d-1");
    expect(await screen.findByLabelText("Quantity of Face cream")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Add a product"), { target: { value: "c" } });
    const taken = await screen.findByRole("button", { name: /Face cream.*Already on this invoice\. Change its quantity in the list below\./ }, { timeout: 3000 });
    expect(taken).toHaveAttribute("aria-disabled", "true");
    expect(taken).toHaveClass("taken");
    const free = screen.getByRole("button", { name: /^Neem soap/ });
    expect(free).not.toHaveAttribute("aria-disabled");
    fireEvent.click(taken);
    expect(screen.getAllByLabelText(/^Quantity of /)).toHaveLength(1);
    fireEvent.click(free);
    expect(await screen.findAllByLabelText(/^Quantity of /)).toHaveLength(2);
  });
});

describe("the invoice date", () => {
  it("takes today's date in India, not UTC or the device's zone", () => {
    expect(todayIst(new Date("2026-11-23T20:16:00Z"))).toBe("2026-11-24"); // 1:46 am IST on the 24th is still the 23rd in UTC
    expect(todayIst(new Date("2026-11-23T18:29:00Z"))).toBe("2026-11-23"); // 11:59 pm IST
    expect(todayIst(new Date("2026-03-31T18:30:00Z"))).toBe("2026-04-01"); // midnight IST starts the new financial year
  });

  it("shows today in grey on a new invoice without saving it, so a later finalize takes that day's date", async () => {
    expect(blankForm().doc_date).toBe("");
    open("/b/b-1/invoices/new");
    const date = await screen.findByLabelText("Invoice date");
    expect(date).toHaveValue(todayIst());
    expect(date).toHaveClass("date-default");
    expect(date).toHaveAttribute("max", todayIst());
    expect(screen.getByText(/until you pick one: the invoice takes the day you create it/)).toBeInTheDocument();
  });

  it("keeps a picked date in normal ink, and clearing it goes back to today in grey", async () => {
    open("/b/b-1/invoices/new");
    const date = await screen.findByLabelText("Invoice date");
    fireEvent.change(date, { target: { value: "2026-11-02" } });
    expect(date).toHaveValue("2026-11-02");
    expect(date).not.toHaveClass("date-default");
    expect(screen.getByText(/Clear the date to use the day you create it/)).toBeInTheDocument();
    fireEvent.change(date, { target: { value: "" } });
    expect(date).toHaveValue(todayIst());
    expect(date).toHaveClass("date-default");
  });

  it("shows a saved draft's own date as it is", async () => {
    server.reply(ONE, { status: 200, body: { ...draft, doc_date: "2026-11-05" } });
    server.reply("/api/v1/b/b-1/customers/c-1", { status: 200, body: delhi });
    open("/b/b-1/invoices/d-1");
    await screen.findByRole("region", { name: "Customer" });
    const date = screen.getByLabelText("Invoice date");
    expect(date).toHaveValue("2026-11-05");
    expect(date).not.toHaveClass("date-default");
  });

  it("opens the calendar when the box is clicked anywhere", async () => {
    open("/b/b-1/invoices/new");
    const date = (await screen.findByLabelText("Invoice date")) as HTMLInputElement;
    const showPicker = vi.fn();
    Object.defineProperty(date, "showPicker", { value: showPicker, configurable: true });
    fireEvent.click(date);
    expect(showPicker).toHaveBeenCalledTimes(1);
  });
});

describe("the PDF preview in the local demo", () => {
  it("works as in the cloud: the demo has its own renderer (#387)", async () => {
    demo.on = true;
    server.reply(ONE, { status: 200, body: draft });
    server.reply("/api/v1/b/b-1/customers/c-1", { status: 200, body: delhi });
    server.reply(`POST ${ONE}/preview`, { status: 202, body: { job_id: "j-1" } });
    open("/b/b-1/invoices/d-1");
    const button = await screen.findByRole("button", { name: "Preview PDF" });
    expect(button).toBeEnabled();
    expect(screen.queryByText(/PDF previews aren't made in the local demo/)).toBeNull();
    fireEvent.click(button);
    await vi.waitFor(() => expect(server.paths()).toContain(`${ONE}/preview`));
  });
});
