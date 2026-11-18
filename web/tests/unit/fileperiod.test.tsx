import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { finishedPeriods } from "../../src/screens/periodfiles/periods";
import { fakeApi } from "./fakeApi";

vi.mock("../../src/features", () => ({ FEATURES: { invoicing: true } }));

const REFRESH = "/api/v1/auth/refresh";
const ME = "/api/v1/me/businesses";
const B = "/api/v1/b/b-1";
const me = (role = "owner") => ({ status: 200, body: { businesses: [{ business_id: "b-1", display_name: "Vashi Essentials", gstin: "19ABCDE1234F1Z5", role }] } });
const filing = (frequency: string) => ({ status: 200, body: { current: { frequency, effective_from: "2026-04-01" }, gstin: "19ABCDE1234F1Z5", history: [], warnings: [], window: {} } });
const NOW = new Date().toISOString().slice(0, 10);
const [current, finished] = finishedPeriods("month", NOW, 1, true);
const gate = (over: Record<string, unknown> = {}) => ({
  kind: "month", period_start: finished.start, period_end: "2026-10-31", ended: true, opens_on: "2026-11-01", can_file: false,
  reasons: ["purchases_uploaded_missing", "invoices_in_portal_missing"],
  confirmations: [
    { item: "purchases_uploaded", confirmed: false, stale: false, at: null },
    { item: "invoices_in_portal", confirmed: false, stale: false, at: null },
  ],
  gstr1_returns: [], due_date: null, due_dates: "Check on the GST portal", ...over,
});

let server: ReturnType<typeof fakeApi>;
beforeEach(() => {
  resetSessionForTests();
  server = fakeApi();
  server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
  server.reply(ME, me(), me());
  server.reply(`${B}/filing-profile`, filing("monthly"));
});
afterEach(() => vi.unstubAllGlobals());

const open = () => {
  window.history.replaceState(null, "", "/b/b-1/file-period");
  render(<App />);
};
const choose = (start: string) => fireEvent.change(screen.getByLabelText("Month"), { target: { value: start } });

describe("file from your own invoices", () => {
  it("keeps the button off, with the reason, until the period has ended", async () => {
    open();
    await screen.findByLabelText("Month");
    server.reply(`GET ${B}/period-gate`, {
      status: 200,
      body: gate({ period_start: current.start, ended: false, opens_on: "2099-01-01", reasons: ["period_not_ended", "purchases_uploaded_missing", "invoices_in_portal_missing"] }),
    });
    choose(current.start);
    expect(await screen.findByText("This period has not ended yet.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Get my GSTR-1 file" })).toBeDisabled();
    expect(screen.getByLabelText(/uploaded all my purchase invoices/)).toBeDisabled();
    expect(screen.getByText(/Filing for this period opens on 2099-01-01/)).toBeInTheDocument();
    expect(screen.getByText(/Due date: Check on the GST portal/)).toBeInTheDocument();
  });

  it("opens the button once both checks stand, and takes the person to the return", async () => {
    open();
    await screen.findByLabelText("Month");
    server.reply(`GET ${B}/period-gate`, { status: 200, body: gate() });
    choose(finished.start);
    const first = await screen.findByLabelText(/uploaded all my purchase invoices/);
    expect(screen.getByRole("button", { name: "Get my GSTR-1 file" })).toBeDisabled();
    server.reply(`PUT ${B}/period-gate`, {
      status: 200,
      body: gate({ reasons: ["invoices_in_portal_missing"], confirmations: [{ item: "purchases_uploaded", confirmed: true, stale: false, at: "2026-11-18T10:00:00Z" }, { item: "invoices_in_portal", confirmed: false, stale: false, at: null }] }),
    });
    fireEvent.click(first);
    await screen.findByText("Confirm that every invoice is in the portal.");
    server.reply(`PUT ${B}/period-gate`, {
      status: 200,
      body: gate({ can_file: true, reasons: [], confirmations: [{ item: "purchases_uploaded", confirmed: true, stale: false, at: "x" }, { item: "invoices_in_portal", confirmed: true, stale: false, at: "x" }] }),
    });
    fireEvent.click(screen.getByLabelText(/Every invoice for this period is in the portal/));
    const button = screen.getByRole("button", { name: "Get my GSTR-1 file" });
    await vi.waitFor(() => expect(button).toBeEnabled());
    const puts = server.sent.filter((s) => s.method === "PUT");
    expect(puts[0].body).toEqual({ kind: "month", start: finished.start, item: "purchases_uploaded", confirmed: true });
    server.reply(`POST ${B}/period-gate/file`, {
      status: 200,
      body: gate({ can_file: true, reasons: [], gstr1_returns: [{ instance_id: "i-1", form: "GSTR1", period_start: finished.start, period_end: "2026-10-31" }] }),
    });
    fireEvent.click(button);
    expect(await screen.findByRole("link", { name: /Open the GSTR1 return/ })).toHaveAttribute("href", "/b/b-1/filing/i-1");
  });

  it("says to confirm again when the records changed after a confirmation", async () => {
    open();
    await screen.findByLabelText("Month");
    server.reply(`GET ${B}/period-gate`, {
      status: 200,
      body: gate({ reasons: ["purchases_uploaded_stale", "invoices_in_portal_missing"], confirmations: [{ item: "purchases_uploaded", confirmed: true, stale: true, at: "x" }, { item: "invoices_in_portal", confirmed: false, stale: false, at: null }] }),
    });
    choose(finished.start);
    expect(await screen.findByText(/changed after you confirmed/)).toBeInTheDocument();
    expect(screen.getByLabelText(/uploaded all my purchase invoices/)).not.toBeChecked();
  });

  it("is not there for a role that cannot prepare returns", async () => {
    server = fakeApi();
    server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
    server.reply(ME, me("billing"), me("billing"));
    open();
    expect(await screen.findByText(/couldn't find that page/)).toBeInTheDocument();
  });
});
