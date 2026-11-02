import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { dayBefore, todayIst } from "../../src/format/dates";
import { fakeApi } from "./fakeApi";

const REFRESH = "/api/v1/auth/refresh";
const ME = "/api/v1/me/businesses";
const UNITS = "/api/v1/b/b-1/units";
const GST = "/api/v1/refdata/gst-rates";
const ONE = "/api/v1/b/b-1/products/p-1";
const RATES = `${ONE}/rates`;
const me = (role: string) => ({ status: 200, body: { businesses: [{ business_id: "b-1", display_name: "Vashi Essentials", gstin: null, role }] } });

const rate = (over: Record<string, unknown> = {}) => ({
  id: "r-1",
  rate: "12",
  valid_from: "2017-07-01",
  valid_until: "2025-09-22",
  voided: false,
  confirmation: null,
  ...over,
});
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
  in_use: true,
  rate_on: { rate: "18", rate_id: "r-2", valid_from: "2025-09-22", confirmed: true },
  warnings: [],
  rate_changed_within_warning_window: false,
  rates: [
    rate(),
    rate({ id: "r-2", rate: "18", valid_from: "2025-09-22", valid_until: null, confirmation: { state: "confirmed", by: "u-1", at: "2025-09-23T10:00:00Z", note: "CA said 18" } }),
    rate({ id: "r-3", rate: "5", valid_from: "2025-01-01", valid_until: null, voided: true }),
  ],
  ...over,
});

let server: ReturnType<typeof fakeApi>;

beforeEach(() => {
  resetSessionForTests();
  server = fakeApi();
  server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
  server.reply(UNITS, { status: 200, body: [{ code: "NOS", name: "Numbers" }] });
  server.reply(GST, { status: 200, body: { on: todayIst(), rates: ["5", "18", "40"] } });
});
afterEach(() => vi.unstubAllGlobals());

async function open(role = "owner", product = detail()) {
  server.reply(ME, me(role));
  server.reply(ONE, { status: 200, body: product });
  window.history.replaceState(null, "", "/b/b-1/products/p-1");
  render(<App />);
  await screen.findByRole("heading", { name: "GST rate history" });
}
const table = () => within(screen.getByRole("heading", { name: "GST rate history" }).closest("section")!);
const rowOf = (text: string) => within(screen.getByRole("table")).getByText(text).closest("tr")!;
const posts = (path: string) => server.sent.filter((s) => s.path === path && s.method === "POST");

describe("the rate history", () => {
  it("shows each rate's last day, strikes out a voided rate, and the owner's own note", async () => {
    await open();
    expect(within(rowOf("12%")).getByText("21-Sep-2025")).toBeInTheDocument(); // the day before the next rate
    expect(within(rowOf("18%")).getByText("Yes (CA said 18)")).toBeInTheDocument();
    const voided = rowOf("5%");
    expect(voided.querySelector("s")).toHaveTextContent("5%");
    expect(within(voided).getByText("Voided")).toBeInTheDocument();
    expect(within(voided).queryByRole("button", { name: "Void" })).toBeNull();
    expect(within(rowOf("12%")).getByText("Not confirmed")).toBeInTheDocument();
    expect(screen.queryByText(/rate changed recently/)).toBeNull();
  });

  it("warns when the rate changed recently", async () => {
    await open("owner", detail({ rate_changed_within_warning_window: true }));
    expect(screen.getByText(/GST rate changed recently/)).toBeInTheDocument();
  });

  it("adds a rate from a date once per attempt, from the rates in force on that date", async () => {
    await open();
    server.reply(RATES, { status: 503 }, { status: 201, body: detail({ version: 4 }) });
    await screen.findByRole("option", { name: "40%" });
    fireEvent.change(screen.getByLabelText("New GST rate"), { target: { value: "40" } });
    fireEvent.click(screen.getByRole("button", { name: "Add rate" }));
    expect(await screen.findByText(/Something went wrong on our side/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Add rate" }));
    await vi.waitFor(() => expect(posts(RATES)).toHaveLength(2));
    await vi.waitFor(() => expect(screen.getByLabelText("New GST rate")).toHaveValue(""));
    const [first, second] = posts(RATES);
    expect(first.body).toEqual({ rate: "40", valid_from: todayIst() });
    expect(second.headers.get("Idempotency-Key")).toBe(first.headers.get("Idempotency-Key"));

    server.reply(RATES, { status: 409, body: { error: { code: "rate_exists_on_date", message: "This product already has a rate from that date" } } });
    fireEvent.change(screen.getByLabelText("New GST rate"), { target: { value: "18" } });
    fireEvent.click(screen.getByRole("button", { name: "Add rate" }));
    expect(await screen.findByText("This product already has a rate from that date")).toBeInTheDocument();
    expect(posts(RATES)[2].headers.get("Idempotency-Key")).not.toBe(first.headers.get("Idempotency-Key"));
  });

  it("voids a rate with a reason, and shows why the last one can't be voided", async () => {
    await open();
    server.reply(`${RATES}/r-2/void`, { status: 409, body: { error: { code: "last_rate", message: "", fix: "Add the correct rate first, then void this one." } } });
    fireEvent.click(within(rowOf("18%")).getByRole("button", { name: "Void" }));
    fireEvent.change(screen.getByLabelText("Why is this rate wrong?"), { target: { value: " Wrong rate " } });
    fireEvent.click(screen.getByRole("button", { name: "Void rate" }));
    expect(await screen.findByText("Add the correct rate first, then void this one.")).toBeInTheDocument();
    expect(posts(`${RATES}/r-2/void`)[0].body).toEqual({ reason: "Wrong rate" });
  });

  it("lets the owner mark and unmark a rate, and sends the note or reason", async () => {
    await open();
    server.reply(`${RATES}/r-1/confirm`, { status: 201, body: detail({ version: 3 }) });
    fireEvent.click(within(rowOf("12%")).getByRole("button", { name: "Mark confirmed" }));
    fireEvent.click(screen.getAllByRole("button", { name: "Mark confirmed" }).at(-1)!);
    await vi.waitFor(() => expect(posts(`${RATES}/r-1/confirm`)).toHaveLength(1));
    expect(posts(`${RATES}/r-1/confirm`)[0].body).toEqual({ note: null });

    server.reply(`${RATES}/r-2/unconfirm`, { status: 201, body: detail() });
    fireEvent.click(within(rowOf("18%")).getByRole("button", { name: "Unmark" }));
    fireEvent.change(screen.getByLabelText("Why are you unmarking it?"), { target: { value: "CA changed advice" } });
    fireEvent.click(screen.getAllByRole("button", { name: "Unmark" }).at(-1)!);
    await vi.waitFor(() => expect(posts(`${RATES}/r-2/unconfirm`)).toHaveLength(1));
    expect(posts(`${RATES}/r-2/unconfirm`)[0].body).toEqual({ reason: "CA changed advice" });
  });

  it("doesn't offer confirming to a billing user, who can still void", async () => {
    await open("billing");
    expect(table().queryByRole("button", { name: "Mark confirmed" })).toBeNull();
    expect(table().queryByRole("button", { name: "Unmark" })).toBeNull();
    expect(within(rowOf("12%")).getByRole("button", { name: "Void" })).toBeInTheDocument();
  });

  it("is locked while the form above has unsaved edits", async () => {
    await open();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Neem bath soap" } });
    expect(screen.getByRole("button", { name: "Add rate" })).toBeDisabled();
    expect(within(rowOf("12%")).getByRole("button", { name: "Void" })).toBeDisabled();
    expect(screen.getByText("Save or undo your changes above before changing rates.")).toBeInTheDocument();
  });
});

describe("dayBefore", () => {
  it("crosses months, years and leap days", () => {
    expect(dayBefore("2026-03-01")).toBe("2026-02-28");
    expect(dayBefore("2024-03-01")).toBe("2024-02-29");
    expect(dayBefore("2026-01-01")).toBe("2025-12-31");
    expect(dayBefore("soon")).toBe("soon");
  });
});
