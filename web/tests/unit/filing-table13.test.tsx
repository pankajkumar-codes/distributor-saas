import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { fakeApi } from "./fakeApi";

const INST = "11111111-1111-4111-8111-111111111111";
const DETAIL = `/api/v1/b/b-1/returns/${INST}`;
const T13 = `${DETAIL}/table13`;
const heads = (t = "0") => ({ taxable_value: t, igst: "0", cgst: "0", sgst: "0", cess: "0" });
const detail = (form = "GSTR1", status = "open") => ({
  status: 200,
  body: {
    instance: { instance_id: INST, form, period: "2026-10", period_label: "October 2026", period_start: "2026-10-01", period_end: "2026-10-31", due_date: null, due_date_confirmed: false, due_date_source_url: null, status },
    draft: true, banner: "Draft", fingerprint: "fp-1", line_items: 1, members_count: 1, report_only: true,
    totals: { liability: heads(), table_12: heads(), gap: heads() },
    sections: [], debit_notes: { count: 0, notice: null }, ca_flags: [], findings: [], finding_groups: [],
    export: { ready: false, to_accept: 0, reasons: [{ code: "C-08", message: "Table 13 is not confirmed." }] },
  },
});
const row = (over: Record<string, unknown> = {}) => ({
  nature: 1, nature_label: "Invoices for outward supply", from_no: "INV/26-27/0001", to_no: "INV/26-27/0008", total_issued: 8, cancelled: 0, net_issue: 8,
  source: "own_live", counted: true, manual: false, missing: 1, needs_ca_check: false, ...over,
});
const t13 = (over: Record<string, unknown> = {}) => ({
  status: 200,
  body: { instance_id: INST, applies: true, required: true, confirmed: false, stale: false, version: null, confirmed_at: null, fingerprint: "fp-1", rows: [row()], ...over },
});

let server: ReturnType<typeof fakeApi>;
beforeEach(() => {
  resetSessionForTests();
  server = fakeApi();
  server.reply("/api/v1/auth/refresh", { status: 200, body: { access_token: "t", expires_in: 3600 } });
});
afterEach(() => vi.unstubAllGlobals());

function open(role = "owner") {
  server.reply("/api/v1/me/businesses", { status: 200, body: { businesses: [{ business_id: "b-1", display_name: "Vashi", gstin: "19ABCDE1234F1Z5", role }] } });
  window.history.replaceState(null, "", `/b/b-1/filing/${INST}`);
  render(<App />);
}

describe("Documents issued (Table 13)", () => {
  it("shows derived rows with the gap hint, and confirms with the typed cancelled count", async () => {
    server.reply(DETAIL, detail(), detail());
    server.reply(T13, t13(), t13({ confirmed: true, version: 1 }));
    server.reply(`PUT ${T13}`, t13({ confirmed: true, version: 1, rows: [row({ cancelled: 1 })] }));
    open();
    expect(await screen.findByRole("heading", { name: "Documents issued Table 13" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Documents issued/ })).toHaveAttribute("aria-selected", "true"); // the step to do next
    expect(screen.getByText("INV/26-27/0001")).toBeInTheDocument();
    expect(screen.getByText(/1 number in this range is not in your files/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/Cancelled, /), { target: { value: "1" } });
    expect(screen.getByText("7")).toBeInTheDocument(); // net issued
    fireEvent.click(screen.getByRole("button", { name: "Confirm these rows" }));
    await waitFor(() => expect(server.sent.some((s) => s.method === "PUT")).toBe(true));
    const put = server.sent.find((s) => s.method === "PUT")!;
    expect(put.body).toEqual({ rows: [{ nature: 1, from_no: "INV/26-27/0001", to_no: "INV/26-27/0008", total_issued: 8, cancelled: 1, counted: true, manual: false }] });
    await waitFor(() => expect(server.paths().filter((p) => p === DETAIL).length).toBe(2)); // the gate is read again
    expect(await screen.findByText(/Version 1/)).toBeInTheDocument();
  });

  it("blocks cancelled above total and an add-a-series row with bad numbers", async () => {
    server.reply(DETAIL, detail());
    server.reply(T13, t13());
    open();
    await screen.findByText("INV/26-27/0001");
    fireEvent.change(screen.getByLabelText(/Cancelled, /), { target: { value: "9" } });
    expect(screen.getByText("Cancelled cannot be more than the total.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm these rows" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Cancelled, /), { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: "Add a series" }));
    expect(screen.getByText(/The from and to numbers must be 1 to 16/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm these rows" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    expect(screen.getByRole("button", { name: "Confirm these rows" })).toBeEnabled();
  });

  it("labels a marketplace series 'Needs CA check', and sends the counted flag the person sets", async () => {
    server.reply(DETAIL, detail());
    server.reply(T13, t13({ rows: [row({ source: "marketplace", needs_ca_check: true, counted: false, missing: 0, from_no: "AMZ0001", to_no: "AMZ0003", total_issued: 3 })] }));
    server.reply(`PUT ${T13}`, t13());
    open();
    expect(await screen.findByText("Needs CA check")).toBeInTheDocument();
    const box = screen.getByLabelText(/Count Invoices for outward supply AMZ0001/) as HTMLInputElement;
    expect(box.checked).toBe(false);
    expect(screen.getByText(/at least one series below is counted/)).toBeInTheDocument();
    fireEvent.click(box);
    fireEvent.click(screen.getByRole("button", { name: "Confirm these rows" }));
    await waitFor(() => expect(server.sent.find((s) => s.method === "PUT")?.body).toMatchObject({ rows: [{ counted: true, from_no: "AMZ0001" }] }));
  });

  it("says so when the documents changed after confirming", async () => {
    server.reply(DETAIL, detail());
    server.reply(T13, t13({ stale: true, confirmed: false, version: 2 }));
    open();
    expect(await screen.findByText(/documents in this period have changed since you confirmed/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm these rows" })).toBeInTheDocument();
  });

  it("adds a manual series and sends it as manual", async () => {
    server.reply(DETAIL, detail());
    server.reply(T13, t13({ rows: [] }));
    server.reply(`PUT ${T13}`, t13());
    open();
    expect(await screen.findByText(/We found no invoice series/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Add a series" }));
    fireEvent.change(screen.getByLabelText(/From, /), { target: { value: "A001" } });
    fireEvent.change(screen.getByLabelText(/To, /), { target: { value: "A005" } });
    fireEvent.change(screen.getByLabelText(/Total issued, /), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm these rows" }));
    await waitFor(() => expect(server.sent.find((s) => s.method === "PUT")?.body).toEqual({ rows: [{ nature: 1, from_no: "A001", to_no: "A005", total_issued: 5, cancelled: 0, counted: true, manual: true }] }));
  });

  it("is absent for IFF, for a locked return and for a role that cannot prepare", async () => {
    for (const [form, status, role] of [["IFF", "open", "owner"], ["GSTR1", "filed_locked", "owner"]] as const) {
      resetSessionForTests();
      server = fakeApi();
      server.reply("/api/v1/auth/refresh", { status: 200, body: { access_token: "t", expires_in: 3600 } });
      server.reply(DETAIL, detail(form, status));
      open(role);
      await waitFor(() => within(screen.getByRole("main")).getByText(/Draft/));
      expect(screen.queryByRole("heading", { name: /Documents issued/ })).toBeNull();
      expect(server.paths()).not.toContain(T13);
      document.body.innerHTML = "";
    }
  });
});
