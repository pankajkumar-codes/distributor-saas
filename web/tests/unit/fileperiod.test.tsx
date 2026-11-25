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
  platform_files: [], gstr1_returns: [], due_date: null, due_dates: "Check on the GST portal", ...over,
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
    expect(screen.getByText(/Filing for this period opens on 01-Jan-2099/)).toBeInTheDocument();
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
      body: gate({ can_file: true, reasons: [], confirmations: [{ item: "purchases_uploaded", confirmed: true, stale: false, at: "2026-11-18T10:00:00Z" }, { item: "invoices_in_portal", confirmed: true, stale: false, at: "2026-11-18T10:00:00Z" }] }),
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
    server.reply(`GET ${B}/returns/i-1`, {
      status: 200,
      body: { instance: { instance_id: "i-1", form: "GSTR1", period: "2026-10", period_label: "October 2026", period_start: finished.start, period_end: "2026-10-31", due_date: null, due_date_confirmed: false, due_date_source_url: null, status: "open" }, export: null, fingerprint: "fp-1" },
    });
    fireEvent.click(button);
    // the return opens right here, with the lock (mark filed) form, and a link to the full return
    expect(await screen.findByRole("heading", { name: "GSTR1 return, October 2026" })).toBeInTheDocument();
    expect(screen.getByLabelText("ARN from the portal")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the full return" })).toHaveAttribute("href", "/b/b-1/filing/i-1");
  });

  it("says to confirm again when the records changed after a confirmation", async () => {
    open();
    await screen.findByLabelText("Month");
    server.reply(`GET ${B}/period-gate`, {
      status: 200,
      body: gate({ reasons: ["purchases_uploaded_stale", "invoices_in_portal_missing"], confirmations: [{ item: "purchases_uploaded", confirmed: true, stale: true, at: "2026-11-18T10:00:00Z" }, { item: "invoices_in_portal", confirmed: false, stale: false, at: null }] }),
    });
    choose(finished.start);
    expect(await screen.findByText(/changed after you confirmed/)).toBeInTheDocument();
    expect(screen.getByLabelText(/uploaded all my purchase invoices/)).not.toBeChecked();
  });

  it("lists the marketplace files still missing and links to the uploads page", async () => {
    open();
    await screen.findByLabelText("Month");
    server.reply(`GET ${B}/period-gate`, {
      status: 200,
      body: gate({ reasons: ["platform_files_missing"], platform_files: [{ platform: "amazon", missing_months: [finished.start.slice(0, 7)] }] }),
    });
    choose(finished.start);
    expect(await screen.findByRole("row", { name: /^Amazon [A-Z][a-z]{2} \d{4} No file yet/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Upload it" })).toHaveAttribute("href", "/b/b-1/uploads");
    expect(screen.getByText("Add the files of the marketplaces you sell on, or say there were no sales.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Get my GSTR-1 file" })).toBeDisabled();
    // saying there were no sales posts that month for that platform, then the gate is read again
    server.reply(`POST ${B}/uploads/none-this-month`, { status: 200, body: { section: "amazon", month: finished.start.slice(0, 7) } });
    server.reply(`GET ${B}/period-gate`, { status: 200, body: gate({ can_file: true, reasons: [], platform_files: [] }) });
    fireEvent.click(screen.getByRole("button", { name: /No Amazon sales in/ }));
    await vi.waitFor(() => expect(screen.getByRole("button", { name: "Get my GSTR-1 file" })).toBeEnabled());
    expect(server.sent.find((x) => x.path === `${B}/uploads/none-this-month`)!.body).toEqual({ section: "amazon", month: finished.start.slice(0, 7) });
    expect(screen.queryByText("Marketplace files")).toBeNull();
  });

  it("shows the due date only when the server confirms it, and says what is upcoming", async () => {
    open();
    await screen.findByLabelText("Month");
    server.reply(`GET ${B}/period-gate`, { status: 200, body: gate({ due_date: "2026-11-11", due_dates: "11 Nov" }) });
    choose(finished.start);
    expect(await screen.findByText(/Due date: 11-Nov-2026/)).toBeInTheDocument();
    expect(screen.queryByText("Upcoming")).toBeNull(); // locking and marking filed are on this page now
  });

  it("is not there for a role that cannot prepare returns", async () => {
    server = fakeApi();
    server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
    server.reply(ME, me("billing"), me("billing"));
    open();
    expect(await screen.findByText(/You don't have access to this page/)).toBeInTheDocument();
  });
});
