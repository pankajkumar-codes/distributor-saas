import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { fakeApi } from "./fakeApi";

const REFRESH = "/api/v1/auth/refresh";
const INST = "22222222-2222-4222-8222-222222222222";
const WS = `/api/v1/b/b-1/returns/${INST}/worksheet`;
const mine = (role = "owner") => ({ status: 200, body: { businesses: [{ business_id: "b-1", display_name: "Vaashi Essentials", gstin: "19ABCDE1234F1Z5", role }] } });
const outward = () => ({
  version: 2, built_at: "2026-11-17T10:00:00+00:00",
  taxable: { taxable_value: "10000.00", igst: "0.00", cgst: "900.00", sgst: "900.00", cess: "0.00" }, taxable_refs: ["a.xlsx row 2", "a.xlsx row 3"],
  inter_state: [{ pos_state_code: "29", unregistered_taxable: "5000.00", unregistered_igst: "900.00", source_refs: ["a.xlsx row 4"] }],
  inter_state_taxable: "5000.00", inter_state_igst: "900.00", zero_rate_rows: 0,
  flags: [{ code: "note_netting", text: "Credit notes are taken off the outward supplies here. Your CA should confirm this." }],
});
const sheet = (over: Record<string, unknown> = {}) => ({
  status: 200,
  body: {
    label: "Worksheet, not a filing", note: "Numbers to check and enter on the GST portal.", offset_note: "Offset and payment are done on the GST portal.",
    available: true, built: true, out_of_date: false, can_build: true, build_blocked_by: null, outward: outward(), entries: {}, entries_seq: null, net_itc: {}, ...over,
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
  server.reply("/api/v1/me/businesses", mine(role));
  window.history.replaceState(null, "", `/b/b-1/filing/${INST}/worksheet`);
  render(<App />);
}
const sentTo = (path: string, method: string) => server.sent.filter((s) => s.path === path && s.method === method);

describe("GSTR-3B worksheet", () => {
  it("shows the label, the portal note, the outward figures and the CA flags, and no net payable or filed wording", async () => {
    server.reply(WS, sheet());
    open();
    expect(await screen.findByText("Worksheet, not a filing")).toBeInTheDocument();
    expect(screen.getByText(/Numbers to check and enter on the GST portal\. Offset and payment are done on the GST portal\./)).toBeInTheDocument();
    expect(screen.getByText("₹10,000.00")).toBeInTheDocument();
    expect(screen.getByText("State code 29")).toBeInTheDocument();
    expect(screen.getByText(/Your CA should confirm this/)).toBeInTheDocument();
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/net payable|ready to file/i);
    expect(text).not.toMatch(/\bfiled\b/i);
  });

  it("asks for the build, then shows the figures; a blocked build is off and says why", async () => {
    server.reply(WS, sheet({ built: false, outward: null, can_build: false, build_blocked_by: "2 items to fix in your GSTR-1 first." }));
    open();
    expect(await screen.findByText("2 items to fix in your GSTR-1 first.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Build the worksheet" })).toBeDisabled();
  });

  it("builds, and reloads the worksheet", async () => {
    server.reply(WS, sheet({ built: false, outward: null }), sheet());
    server.reply(`${WS}/build`, { status: 200, body: outward() });
    open();
    fireEvent.click(await screen.findByRole("button", { name: "Build the worksheet" }));
    await waitFor(() => expect(sentTo(`${WS}/build`, "POST")).toHaveLength(1));
    expect(await screen.findByText("₹10,000.00")).toBeInTheDocument();
  });

  it("says when the GSTR-1 has changed since the build and keeps the rebuild one click away", async () => {
    server.reply(WS, sheet({ out_of_date: true }));
    open();
    expect(await screen.findByText(/Your GSTR-1 has changed since this worksheet was built/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Build again" })).toBeEnabled();
  });

  it("shows no figures when the plan does not allow them", async () => {
    server.reply(WS, sheet({ available: false, outward: null }));
    open();
    expect(await screen.findByText(/figures are not available on your plan yet/)).toBeInTheDocument();
    expect(screen.queryByText("₹10,000.00")).toBeNull();
    expect(screen.queryByRole("button", { name: "Save what I entered" })).toBeNull();
  });

  it("saves what was typed as text against the save it was based on, with central tax typed once", async () => {
    server.reply(WS, sheet({ entries: { "t4a.other.cgst": "100.00", "t4a.other.sgst": "100.00" }, entries_seq: 3, net_itc: { igst: "0.00", cgst: "100.00", sgst: "100.00", cess: "0.00" } }));
    server.reply(`${WS}/entries`, { status: 200, body: { entries: {}, entries_seq: 4, net_itc: {} } });
    open();
    const other = (await screen.findByText("(5) All other ITC")).closest("fieldset") as HTMLElement;
    const central = within(other).getByLabelText("Central Tax (State/UT Tax is the same)");
    expect(central).toHaveValue("100.00");
    expect(within(other).queryByLabelText("State/UT Tax")).toBeNull();
    fireEvent.change(central, { target: { value: "250.50" } });
    fireEvent.click(screen.getByRole("button", { name: "Save what I entered" }));
    await waitFor(() => expect(sentTo(`${WS}/entries`, "PUT")).toHaveLength(1));
    expect(sentTo(`${WS}/entries`, "PUT")[0].body).toEqual({ entries: { "t4a.other.cgst": "250.50" }, based_on_seq: 3 });
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
  });

  it("puts the server's words under the box it names", async () => {
    server.reply(WS, sheet());
    server.reply(`${WS}/entries`, { status: 422, body: { error: { code: "entry_invalid", message: "x", field: "t4b.rev_other.igst", fix: "An amount cannot be negative." } } });
    open();
    const rev = (await screen.findByText("(2) Others", { selector: "legend" })).closest("fieldset") as HTMLElement;
    fireEvent.change(within(rev).getByLabelText("Integrated Tax"), { target: { value: "-5" } });
    fireEvent.click(screen.getByRole("button", { name: "Save what I entered" }));
    expect((await within(rev).findAllByText("An amount cannot be negative.")).length).toBeGreaterThan(0);
  });

  it("is a not-found page for billing, which the server refuses", async () => {
    open("billing");
    expect(await screen.findByText("We couldn't find that page")).toBeInTheDocument();
    expect(sentTo(WS, "GET")).toHaveLength(0);
  });
});
