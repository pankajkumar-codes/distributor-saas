import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { fakeApi } from "./fakeApi";

const REFRESH = "/api/v1/auth/refresh";
const BIZ = "/api/v1/b/b-1/returns";
const INST = "11111111-1111-4111-8111-111111111111";
const DETAIL = `${BIZ}/${INST}`;
const B2B = `${DETAIL}/sections/b2b`;
const mine = (role = "owner") => ({
  status: 200,
  body: { businesses: [{ business_id: "b-1", display_name: "Vashi Essentials", gstin: "19ABCDE1234F1Z5", role }] },
});
const heads = (t = "0") => ({ taxable_value: t, igst: "0", cgst: "0", sgst: "0", cess: "0" });
const finding = (code: string, level: string, n: number, extra: Record<string, unknown> = {}) => ({
  code, level, message: `${code} message ${n}`, source_refs: [`a.xlsx row ${n}`], subject_fp: `${code}-${n}`, needs_ca_check: false, ...extra,
});
const detail = (over: Record<string, unknown> = {}) => ({
  status: 200,
  body: {
    instance: { instance_id: INST, form: "GSTR1", period: "2026-10", period_label: "October 2026", period_start: "2026-10-01", period_end: "2026-10-31", due_date: null, due_date_confirmed: false, due_date_source_url: null, status: "open" },
    draft: true, banner: "Draft: not filed. Check every figure against your own records before you use it.", fingerprint: "fp-1", line_items: 3, members_count: 2, report_only: true,
    totals: { liability: { ...heads("200.00"), cgst: "18.00", sgst: "18.00" }, table_12: heads("200.00"), gap: heads() },
    sections: [
      { name: "b2b", rows_count: 1, totals: heads("200.00") }, { name: "b2cl", rows_count: 0, totals: heads() }, { name: "b2cs", rows_count: 0, totals: heads() },
      { name: "cdnr", rows_count: 0, totals: heads() }, { name: "cdnur", rows_count: 0, totals: heads() }, { name: "hsn_b2b", rows_count: 0, totals: heads() }, { name: "hsn_b2c", rows_count: 0, totals: heads() },
    ],
    debit_notes: { count: 0, notice: null }, ca_flags: [],
    findings: [finding("A-01", "warn", 2, { needs_ca_check: true }), finding("A-01", "warn", 3, { needs_ca_check: true }), finding("C-01", "block", 4)],
    finding_groups: [{ code: "A-01", level: "warn", count: 2, needs_ca_check: true }, { code: "C-01", level: "block", count: 1, needs_ca_check: false }],
    ...over,
  },
});
const page = (fingerprint = "fp-1", extra: Record<string, unknown> = {}) => ({
  status: 200,
  body: {
    section: "b2b", fingerprint, has_more: false, next_cursor: null,
    rows: [{ recipient_gstin: "27ABCDE1234F1Z5", recipient_name: "Acme", invoice_number: "INV-3", invoice_date: "2026-10-05", invoice_value: "236.00", pos_state_code: "19", rate: "18", taxable_value: "200.00", igst: "0", cgst: "18.00", sgst: "18.00", cess: "0", source_refs: ["a.xlsx row 2"] }],
    ...extra,
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
  window.history.replaceState(null, "", `/b/b-1/filing/${INST}`);
  render(<App />);
}

describe("A return (read-only)", () => {
  it("shows the draft banner, totals, and checks with plain words, blocking first, A-01 as one group", async () => {
    server.reply(DETAIL, detail());
    open();
    expect(await screen.findByText(/Draft: not filed/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /GSTR-1 for October 2026/ })).toBeInTheDocument();
    const summaries = screen.getAllByText(/Fix before you use this|Please check/).map((e) => e.textContent);
    expect(summaries[0]).toBe("Fix before you use this"); // blocking group first
    expect(screen.getByText("HSN code missing")).toBeInTheDocument();
    const tax = screen.getByText("Tax does not equal taxable value times rate").closest("details")!;
    expect(within(tax).getByText("2 items")).toBeInTheDocument();
    expect(within(tax).getByText("Needs a CA check")).toBeInTheDocument();
    expect(within(tax).getByText(/A-01 message 2/)).toBeInTheDocument();
    expect(screen.getByText(/1 item needs fixing/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /download|export|file/i })).toBeNull();
  });

  it("loads a section's rows only when it is opened, with the source of each row", async () => {
    server.reply(DETAIL, detail());
    server.reply(B2B, page());
    open();
    await screen.findByText(/Draft: not filed/);
    expect(server.paths()).not.toContain(B2B);
    const section = screen.getByText("Sales to businesses (B2B)").closest("details")!;
    section.open = true;
    fireEvent(section, new Event("toggle"));
    expect(await within(section).findByText("INV-3")).toBeInTheDocument();
    expect(within(section).getByText("₹236.00")).toBeInTheDocument();
    expect(within(section).getByText("a.xlsx row 2")).toBeInTheDocument();
  });

  it("stops and asks for a reload when a page comes from a different build", async () => {
    server.reply(DETAIL, detail());
    server.reply(B2B, page("fp-2"));
    open();
    await screen.findByText(/Draft: not filed/);
    const section = screen.getByText("Sales to businesses (B2B)").closest("details")!;
    section.open = true;
    fireEvent(section, new Event("toggle"));
    expect(await within(section).findByText(/This return changed while you were reading it/)).toBeInTheDocument();
    expect(within(section).queryByText("INV-3")).toBeNull();
  });

  it("stops when a later page comes from a different build, and hides the rows already shown", async () => {
    server.reply(DETAIL, detail());
    server.reply(B2B, page("fp-1", { has_more: true, next_cursor: "100" }), page("fp-2"));
    open();
    await screen.findByText(/Draft: not filed/);
    const section = screen.getByText("Sales to businesses (B2B)").closest("details")!;
    section.open = true;
    fireEvent(section, new Event("toggle"));
    expect(await within(section).findByText("INV-3")).toBeInTheDocument();
    fireEvent.click(within(section).getByRole("button", { name: "Show more rows" }));
    expect(await within(section).findByText(/This return changed while you were reading it/)).toBeInTheDocument();
    expect(within(section).queryByText("INV-3")).toBeNull();
  });

  it("shows the debit-note notice", async () => {
    server.reply(DETAIL, detail({ debit_notes: { count: 2, notice: "2 debit note(s) are not in this return yet. They need a CA check." } }));
    open();
    expect(await screen.findByText(/2 debit note\(s\) are not in this return yet/)).toBeInTheDocument();
  });

  it("is a not-found page for a 404, such as a billing user or another business's id", async () => {
    server.reply(DETAIL, { status: 404, body: { error: { code: "not_found", message: "Not found." } } });
    open("billing");
    expect(await screen.findByText("We couldn't find that page")).toBeInTheDocument();
  });

  it("links to the return from the filing home for an owner and not for billing", async () => {
    const row = { instance_id: INST, form: "GSTR1", period: "2026-10", period_label: "October 2026", period_start: "2026-10-01", period_end: "2026-10-31", due_date: null, due_date_confirmed: false, due_date_source_url: null, status: "open" };
    const list = { status: 200, body: { fy: "2026-27", filing_frequency: "monthly", returns: [row] } };
    for (const [role, linked] of [["owner", true], ["billing", false]] as const) {
      resetSessionForTests();
      server = fakeApi();
      server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
      server.reply("/api/v1/me/businesses", mine(role));
      server.reply(BIZ, list, list);
      window.history.replaceState(null, "", "/b/b-1/filing");
      const view = render(<App />);
      await screen.findByText("October 2026");
      expect(screen.queryByRole("link", { name: "Review the draft" }) !== null).toBe(linked);
      view.unmount();
    }
  });
});
