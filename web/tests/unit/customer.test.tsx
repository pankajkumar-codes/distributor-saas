import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { changedKeys, patchBody, rebase, type Values } from "../../src/screens/customers/CustomerPage";
import { fakeApi } from "./fakeApi";

const REFRESH = "/api/v1/auth/refresh";
const ME = "/api/v1/me/businesses";
const STATES = "/api/v1/refdata/state-codes";
const LIST = "/api/v1/b/b-1/customers";
const ONE = "/api/v1/b/b-1/customers/c-1";
const me = { status: 200, body: { businesses: [{ business_id: "b-1", display_name: "Vashi Essentials", gstin: null, role: "owner" }] } };
const states = { status: 200, body: { on: "2026-11-02", states: [{ code: "19", name: "West Bengal" }, { code: "27", name: "Maharashtra" }] } };

const address = (over: Record<string, unknown> = {}) => ({ line1: "4 Park Street", line2: null, city: "Kolkata", pin: "700016", state_code: "19", ...over });
const detail = (over: Record<string, unknown> = {}) => ({
  id: "c-1",
  name: "Sharma Traders",
  gstin: "19AAAAA0000A1Z5",
  gstin_state_code: "19",
  billing: address(),
  delivery_same_as_billing: true,
  delivery: null,
  credit_days: 30,
  status: "active",
  version: 3,
  in_use: false,
  warnings: [],
  ...over,
});

let server: ReturnType<typeof fakeApi>;

beforeEach(() => {
  resetSessionForTests();
  server = fakeApi();
  server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
  server.reply(ME, me);
  server.reply(STATES, states);
});
afterEach(() => vi.unstubAllGlobals());

function open(path: string) {
  window.history.replaceState(null, "", path);
  render(<App />);
}
const group = (name: string) => within(screen.getByRole("group", { name }));
const type = (label: string, value: string, scope: Pick<typeof screen, "getByLabelText"> = screen) => fireEvent.change(scope.getByLabelText(label), { target: { value } });
const sent = (path: string, method: string) => server.sent.filter((s) => s.path === path && s.method === method);

describe("a new customer", () => {
  it("is created once per form, with delivery null when it's the billing address", async () => {
    open("/b/b-1/customers/new");
    await screen.findByRole("option", { name: "West Bengal (19)" });
    server.reply(LIST, { status: 503 }, { status: 201, body: detail({ version: 1 }) });
    server.reply(ONE, { status: 200, body: detail({ version: 1 }) });
    type("Name", " Sharma Traders ");
    type("GSTIN (optional)", "19AAAAA0000A1Z5");
    type("Address line 1", "4 Park Street");
    type("PIN code", "700016");
    type("Credit days", "30");
    fireEvent.click(screen.getByRole("button", { name: "Add customer" }));
    expect(await screen.findByText(/Something went wrong on our side/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Add customer" }));
    expect(await screen.findByRole("heading", { name: "Sharma Traders" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/b/b-1/customers/c-1");
    const [first, second] = sent(LIST, "POST");
    expect(second.headers.get("Idempotency-Key")).toBe(first.headers.get("Idempotency-Key"));
    expect(first.body).toEqual({
      name: "Sharma Traders",
      gstin: "19AAAAA0000A1Z5",
      billing: { line1: "4 Park Street", line2: null, city: null, pin: "700016", state_code: null },
      delivery_same_as_billing: true,
      delivery: null,
      credit_days: 30,
    });
  });

  it("sends a delivery address when it differs, and shows the server's words on the field it names", async () => {
    open("/b/b-1/customers/new");
    await screen.findByRole("option", { name: "West Bengal (19)" });
    server.reply(LIST, { status: 422, body: { error: { code: "state_code_required", message: "Choose the state", field: "delivery.state_code" } } });
    type("Name", "Asha Stores");
    fireEvent.click(screen.getByRole("checkbox", { name: "Deliver to the billing address" }));
    type("City or town", "Pune", group("Delivery address"));
    fireEvent.click(screen.getByRole("button", { name: "Add customer" }));
    expect(await group("Delivery address").findByText("Choose the state")).toBeInTheDocument();
    expect(group("Delivery address").getByLabelText("State")).toHaveAttribute("aria-invalid", "true");
    expect(sent(LIST, "POST")[0].body).toMatchObject({
      gstin: null,
      delivery_same_as_billing: false,
      delivery: { line1: null, line2: null, city: "Pune", pin: null, state_code: null },
    });
  });

  it("shows a GSTIN error in the server's words, and refuses credit days that aren't a whole number without asking", async () => {
    open("/b/b-1/customers/new");
    await screen.findByRole("option", { name: "West Bengal (19)" });
    type("Credit days", "30.5");
    fireEvent.click(screen.getByRole("button", { name: "Add customer" }));
    expect(screen.getByText("Use a whole number of days, such as 0 or 30.")).toBeInTheDocument();
    expect(sent(LIST, "POST")).toHaveLength(0);
    server.reply(LIST, { status: 422, body: { error: { code: "gstin_invalid", message: "GSTIN has 14 characters; it needs 15", field: "gstin" } } });
    type("Credit days", "0");
    type("GSTIN (optional)", "19AAAAA0000A1Z");
    fireEvent.click(screen.getByRole("button", { name: "Add customer" }));
    expect(await screen.findByText("GSTIN has 14 characters; it needs 15")).toBeInTheDocument();
    expect(screen.getByLabelText("GSTIN (optional)")).toHaveAttribute("aria-invalid", "true");
  });
});

describe("editing a customer", () => {
  it("sends only what changed, an address whole, with the version it was opened at", async () => {
    server.reply(ONE, { status: 200, body: detail() });
    open("/b/b-1/customers/c-1");
    await screen.findByRole("heading", { name: "Sharma Traders" });
    server.reply(ONE, { status: 200, body: detail({ version: 4, billing: address({ city: "Howrah" }) }) });
    type("City or town", "Howrah");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText(/Saved\. Invoices already finalized keep/)).toBeInTheDocument();
    const [patch] = sent(ONE, "PATCH");
    expect(patch.body).toEqual({ billing: { line1: "4 Park Street", line2: null, city: "Howrah", pin: "700016", state_code: "19" } });
    expect(patch.headers.get("If-Match")).toBe("3");
  });

  it("after someone else saved first, keeps both people's changes to different fields", async () => {
    server.reply(ONE, { status: 200, body: detail() });
    open("/b/b-1/customers/c-1");
    await screen.findByRole("heading", { name: "Sharma Traders" });
    server.reply(
      ONE,
      { status: 409, body: { error: { code: "stale_record", message: "Someone changed this customer since you opened it" } } },
      { status: 200, body: detail({ credit_days: 45, version: 4 }) },
      { status: 200, body: detail({ name: "Sharma & Sons", credit_days: 45, version: 5 }) },
    );
    type("Name", "Sharma & Sons");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText(/Someone changed this customer since you opened it/)).toBeInTheDocument();
    expect(await screen.findByText("Someone else changed this.")).toBeInTheDocument();
    expect(screen.getByLabelText("Credit days")).toHaveValue("45");
    expect(screen.getByLabelText("Name")).toHaveValue("Sharma & Sons");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await screen.findByText(/Saved\./);
    const patches = sent(ONE, "PATCH");
    expect(patches[1].headers.get("If-Match")).toBe("4");
    expect(patches[1].body).toEqual({ name: "Sharma & Sons" });
  });

  it("shows the server's warnings beside the field they name", async () => {
    server.reply(ONE, {
      status: 200,
      body: detail({ warnings: [{ code: "billing_state_differs", field: "billing.state_code", message: "The billing state isn't the GSTIN's state. Place of supply follows the GSTIN" }] }),
    });
    open("/b/b-1/customers/c-1");
    expect(await screen.findByText(/Place of supply follows the GSTIN/)).toBeInTheDocument();
  });

  it("won't archive over unsaved edits, and deletes an unused customer only after asking", async () => {
    server.reply(ONE, { status: 200, body: detail() }, { status: 204 });
    server.reply(LIST, { status: 200, body: { items: [], has_more: false } });
    open("/b/b-1/customers/c-1");
    await screen.findByRole("heading", { name: "Sharma Traders" });
    type("Credit days", "60");
    expect(screen.getByRole("button", { name: "Archive" })).toBeDisabled();
    type("Credit days", "30");
    expect(screen.getByRole("button", { name: "Archive" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    fireEvent.click(screen.getByRole("button", { name: "Yes, delete" }));
    await screen.findByRole("heading", { name: "Customers" });
    expect(sent(ONE, "DELETE")[0].headers.get("If-Match")).toBe("3");
  });

  it("doesn't offer Delete for a customer on invoices", async () => {
    server.reply(ONE, { status: 200, body: detail({ in_use: true }) });
    open("/b/b-1/customers/c-1");
    await screen.findByRole("heading", { name: "Sharma Traders" });
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
    expect(screen.getByText(/can be archived but not deleted/)).toBeInTheDocument();
  });
});

describe("helpers", () => {
  const a = { line1: "4 Park Street", line2: "", city: "Kolkata", pin: "700016", state_code: "19" };
  const v: Values = { name: "S", gstin: "", credit_days: "30", same: true, billing: a, delivery: { ...a, line1: "" } };

  it("treats an address as one field, and ignores the delivery address while it's the billing one", () => {
    expect(changedKeys(v, { ...v, name: " S " })).toEqual([]);
    expect(changedKeys(v, { ...v, delivery: { ...a, city: "Pune" } })).toEqual([]);
    expect(changedKeys(v, { ...v, billing: { ...a, pin: "700017" } })).toEqual(["billing"]);
  });

  it("sends delivery whole when it stops being the billing address, and nothing of it when it starts", () => {
    const apart = { ...v, same: false, delivery: { ...a, city: "Pune" } };
    expect(patchBody(v, apart)).toEqual({
      delivery_same_as_billing: false,
      delivery: { line1: "4 Park Street", line2: null, city: "Pune", pin: "700016", state_code: "19" },
    });
    expect(patchBody(apart, { ...apart, same: true })).toEqual({ delivery_same_as_billing: true });
    expect(patchBody(v, { ...v, gstin: " ", credit_days: "45" })).toEqual({ credit_days: 45 });
  });

  it("rebases the user's edits onto a newer version", () => {
    expect(rebase(v, { ...v, credit_days: "45" }, { ...v, name: "T" })).toEqual({ ...v, name: "T", credit_days: "45" });
  });
});
