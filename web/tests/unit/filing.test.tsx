import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { quarterStartIst } from "../../src/format/dates";
import { fakeApi } from "./fakeApi";

const REFRESH = "/api/v1/auth/refresh";
const ME = "/api/v1/me/businesses";
const PROFILE = "/api/v1/b/b-1/filing-profile";
const CHANGE = `${PROFILE}/frequency`;
const GSTIN = "19ABCDE1234F1Z5";
const me = (role = "owner") => ({
  status: 200,
  body: { businesses: [{ business_id: "b-1", display_name: "Vashi Essentials", gstin: GSTIN, role }] },
});
// A quarter the server names that is neither this quarter nor anything the web could work out.
const NEXT = "2099-04-01";
const row = (over: Record<string, unknown> = {}) => ({
  id: "f-1",
  gstin: GSTIN,
  frequency: "quarterly",
  effective_from: "2026-04-01",
  chosen_at: "2026-10-31T20:00:00Z", // 1 Nov in India
  warnings: [],
  ...over,
});
const profile = (over: Record<string, unknown> = {}) => ({
  status: 200,
  body: {
    gstin: GSTIN,
    current: { frequency: "quarterly", effective_from: "2026-04-01" },
    history: [row()],
    window: { for_quarter: NEXT, opens: "2099-03-01", closes: "2099-04-30" },
    warnings: [],
    ...over,
  },
});

let server: ReturnType<typeof fakeApi>;
beforeEach(() => {
  resetSessionForTests();
  server = fakeApi();
  server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
});
afterEach(() => vi.unstubAllGlobals());

function open(role = "owner") {
  server.reply(ME, me(role));
  window.history.replaceState(null, "", "/b/b-1/settings/filing");
  render(<App />);
}
const sent = () => server.sent.filter((s) => s.path === CHANGE && s.method === "POST");

describe("filing frequency", () => {
  it("shows the current frequency, the server's window and the history", async () => {
    server.reply(PROFILE, profile());
    open();
    expect(await screen.findByText("Every quarter (QRMP), from 01-Apr-2026.")).toBeInTheDocument();
    expect(screen.getByText(/quarter starting 01-Apr-2099 can be made on the GST portal from 01-Mar-2099 to 30-Apr-2099/)).toBeInTheDocument();
    const history = screen.getByRole("table");
    expect(within(history).getByText("01-Nov-2026")).toBeInTheDocument();
  });

  it("offers only the server's quarter and this one, and changes the frequency with the server's warnings", async () => {
    server.reply(PROFILE, profile(), profile({ current: { frequency: "monthly", effective_from: NEXT }, history: [row({ id: "f-2", frequency: "monthly", effective_from: NEXT }), row()] }));
    server.reply(CHANGE, { status: 422, body: { error: { code: "effective_from_too_far", message: "choose a quarter starting 2027-01-01 or earlier", field: "effective_from" } } }, {
      status: 201,
      body: { row: row({ id: "f-2", frequency: "monthly", effective_from: NEXT }), warnings: ["outside_window"], superseded_instances: ["r-1", "r-2"] },
    });
    open();
    await screen.findByText("Every quarter (QRMP), from 01-Apr-2026.");
    const starts = screen.getByRole("group", { name: "Starting from the quarter that begins" });
    expect(within(starts).getAllByRole("radio").map((r) => (r as HTMLInputElement).value)).toEqual([quarterStartIst(), NEXT].sort());
    expect(within(starts).getByRole("radio", { name: "01-Apr-2099" })).toBeChecked();

    fireEvent.click(screen.getByRole("radio", { name: "Every month" }));
    fireEvent.click(screen.getByRole("button", { name: "Save frequency" }));
    expect(await within(starts).findByText("choose a quarter starting 2027-01-01 or earlier")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save frequency" }));

    expect(await screen.findByText(/Saved: Every month, from 01-Apr-2099\. 2 empty return periods were replaced to match\./)).toBeInTheDocument();
    expect(screen.getByText(/may fall outside the period when it can be changed on the GST portal/)).toBeInTheDocument();
    expect(await screen.findByText("Every month, from 01-Apr-2099.")).toBeInTheDocument();
    const [first, second] = sent();
    expect(first.body).toEqual({ frequency: "monthly", effective_from: NEXT });
    expect(second.headers.get("Idempotency-Key")).toBe(first.headers.get("Idempotency-Key")); // same choice, same key
  });

  it("uses a new key for a new choice", async () => {
    server.reply(PROFILE, profile());
    server.reply(CHANGE, { status: 503 }, { status: 503 });
    open();
    await screen.findByText("Every quarter (QRMP), from 01-Apr-2026.");
    fireEvent.click(screen.getByRole("radio", { name: "Every month" }));
    fireEvent.click(screen.getByRole("button", { name: "Save frequency" }));
    expect(await screen.findByText(/Something went wrong on our side/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "Every quarter (QRMP)" }));
    fireEvent.click(screen.getByRole("button", { name: "Save frequency" }));
    await vi.waitFor(() => expect(sent()).toHaveLength(2));
    expect(sent()[1].headers.get("Idempotency-Key")).not.toBe(sent()[0].headers.get("Idempotency-Key"));
  });

  it("shows no window dates when the server doesn't know them, only its warning", async () => {
    server.reply(PROFILE, profile({ current: null, history: [], window: { for_quarter: NEXT, opens: null, closes: null }, warnings: ["window_unknown"] }));
    open();
    expect(await screen.findByText("You haven't chosen a filing frequency yet.")).toBeInTheDocument();
    expect(screen.getByText(/We can't show the dates for changing your filing frequency yet/)).toBeInTheDocument();
    expect(screen.queryByText(/can be made on the GST portal/)).toBeNull();
    expect(screen.getByRole("heading", { name: "Choose frequency" })).toBeInTheDocument();
  });

  it("asks for the GSTIN first when the business has none", async () => {
    server.reply(PROFILE, profile({ gstin: null, current: null, history: [] }));
    open();
    expect(await screen.findByRole("link", { name: "business details" })).toHaveAttribute("href", "/b/b-1/settings/company");
    expect(screen.queryByRole("button", { name: "Save frequency" })).toBeNull();
  });

  it("shows the values but no form to a role that can't change settings", async () => {
    server.reply(PROFILE, profile());
    open("ca");
    await screen.findByText("Every quarter (QRMP), from 01-Apr-2026.");
    expect(screen.queryByRole("button", { name: "Save frequency" })).toBeNull();
  });

  it("is NotFound for another business", async () => {
    server.reply(ME, { status: 200, body: { businesses: [] } });
    window.history.replaceState(null, "", "/b/b-1/settings/filing");
    render(<App />);
    expect(await screen.findByText(/couldn't find that page/i)).toBeInTheDocument();
    expect(server.paths()).not.toContain(PROFILE);
  });
});
