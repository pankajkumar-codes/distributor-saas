import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { fakeApi } from "./fakeApi";

const REFRESH = "/api/v1/auth/refresh";
const INST = "11111111-1111-4111-8111-111111111111";
const DETAIL = `/api/v1/b/b-1/returns/${INST}`;
const mine = (role = "owner") => ({
  status: 200,
  body: { businesses: [{ business_id: "b-1", display_name: "Vaashi Essentials", gstin: "19ABCDE1234F1Z5", role }] },
});
const heads = (t = "0") => ({ taxable_value: t, igst: "0", cgst: "0", sgst: "0", cess: "0" });
const warn = (n: number, accepted = false) => ({ code: "C-16", level: "warn", message: `C-16 message ${n}`, source_refs: [`a.xlsx row ${n}`], subject_fp: `C-16-${n}`, needs_ca_check: true, accepted });
const block = { code: "C-01", level: "block", message: "C-01 message", source_refs: ["a.xlsx row 9"], subject_fp: "C-01-9", needs_ca_check: false, accepted: false };
const instance = (over: Record<string, unknown> = {}) => ({
  instance_id: INST, form: "GSTR1", period: "2026-10", period_label: "October 2026", period_start: "2026-10-01", period_end: "2026-10-31",
  due_date: null, due_date_confirmed: false, due_date_source_url: null, status: "open", filed_on: null, arn: null, ...over,
});
const detail = (over: Record<string, unknown> = {}, inst: Record<string, unknown> = {}) => ({
  status: 200,
  body: {
    instance: instance(inst), draft: true, banner: "Draft: not filed.", fingerprint: "fp-1", line_items: 3, members_count: 2, report_only: false,
    totals: { liability: heads("200.00"), table_12: heads("200.00"), gap: heads() },
    sections: ["b2b", "b2cl", "b2cs", "cdnr", "cdnur", "hsn_b2b", "hsn_b2c"].map((name) => ({ name, rows_count: 0, totals: heads() })),
    debit_notes: { count: 0, notice: null }, ca_flags: [],
    findings: [warn(2), warn(3)],
    finding_groups: [{ code: "C-16", level: "warn", count: 2, needs_ca_check: true, accepted: 0 }],
    export: { ready: false, reasons: [], to_accept: 2 },
    ...over,
  },
});
const ready = { ready: true, reasons: [], to_accept: 0 };
const fileOut = (over: Record<string, unknown> = {}) => ({
  status: 200,
  body: {
    status: "ready", version: 1, files: [{ part: 1, rows: 12, size_bytes: 900, url: "https://files.example/part1" }],
    not_in_file: ["Table 13 (documents issued)"], unverified_tables: [], portal_tested: false, ready_to_upload: false, ...over,
  },
});

let server: ReturnType<typeof fakeApi>;
beforeEach(() => {
  resetSessionForTests();
  server = fakeApi();
  server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
});
afterEach(() => vi.unstubAllGlobals());

function open(role = "owner", tab = "file") {
  server.reply("/api/v1/me/businesses", mine(role));
  window.history.replaceState(null, "", `/b/b-1/filing/${INST}?tab=${tab}`);
  render(<App />);
}
const sentTo = (path: string, method = "POST") => server.sent.filter((s) => s.path === path && s.method === method);

describe("Accepting warnings", () => {
  it("accepts a check's warnings as shown with a reason, and never offers it for a block", async () => {
    server.reply(DETAIL, detail({ findings: [warn(2), warn(3), block], finding_groups: [{ code: "C-16", level: "warn", count: 2, needs_ca_check: true, accepted: 0 }, { code: "C-01", level: "block", count: 1, needs_ca_check: false, accepted: 0 }] }), detail({ findings: [warn(2, true), warn(3, true)], finding_groups: [{ code: "C-16", level: "warn", count: 2, needs_ca_check: true, accepted: 2 }], export: ready }));
    server.reply(`${DETAIL}/check-acceptances`, { status: 200, body: { check_code: "C-16", accepted: 2 } });
    open("owner", "checks");
    await screen.findByText(/Draft: not filed/);
    expect(screen.getAllByRole("button", { name: "Accept as shown" })).toHaveLength(1); // C-16 only
    expect(screen.getByText(/can't be accepted/)).toBeInTheDocument();
    const button = screen.getByRole("button", { name: "Accept as shown" });
    expect(button).toBeDisabled(); // a reason first
    fireEvent.change(screen.getByLabelText("Why is this fine to file as it is?"), { target: { value: "CA will confirm in November" } });
    fireEvent.click(button);
    await waitFor(() => expect(sentTo(`${DETAIL}/check-acceptances`)).toHaveLength(1));
    expect(sentTo(`${DETAIL}/check-acceptances`)[0].body).toEqual({ check_code: "C-16", note: "CA will confirm in November" });
    await waitFor(() => expect(screen.queryByRole("button", { name: "Accept as shown" })).toBeNull());
    expect(screen.getAllByText("Accepted").length).toBeGreaterThan(0);
  });

  it("is a not-found page for a role the server refuses, so nothing is offered", async () => {
    server.reply(DETAIL, { status: 404, body: { error: { code: "not_found", message: "Not found." } } });
    open("billing");
    expect(await screen.findByText("You don't have access to this page")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Accept as shown" })).toBeNull();
  });
});

describe("Making the file", () => {
  it("is off while the return is not ready, says why, and says how many warnings still need accepting", async () => {
    server.reply(DETAIL, detail({ export: { ready: false, reasons: [{ code: "blocks", message: "1 item to fix first." }], to_accept: 2 } }));
    open();
    expect(await screen.findByText("1 item to fix first.")).toBeInTheDocument();
    expect(screen.getByText(/2 warnings still need you to accept them/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Make my GSTR-1 file" })).toBeDisabled();
  });

  it("makes the file, waits for it, and says it has not been through the portal", async () => {
    server.reply(DETAIL, detail({ export: ready, findings: [], finding_groups: [] }));
    server.reply(`${DETAIL}/exports`, { status: 202, body: { job_id: "job-1" } });
    server.reply(`${DETAIL}/exports/job-1`, { status: 200, body: { status: "preparing", files: [], not_in_file: [], unverified_tables: [], portal_tested: false, ready_to_upload: false } }, fileOut({ unverified_tables: ["cdnr"] }));
    open();
    fireEvent.click(await screen.findByRole("button", { name: "Make my GSTR-1 file" }));
    expect(await screen.findByText("Making your file…")).toBeInTheDocument();
    const link = await screen.findByRole("link", { name: "Download the file" }, { timeout: 5000 });
    expect(link).toHaveAttribute("href", "https://files.example/part1");
    expect(screen.getAllByText(/This file has not been through the GST portal yet/)).toHaveLength(1);
    expect(screen.getByText(/We are least sure of these tables: CDNR/)).toBeInTheDocument();
    expect(screen.getByText(/Table 13 \(documents issued\)/)).toBeInTheDocument();
    expect(screen.queryByText(/ready to upload/i)).toBeNull();
  });

  it("links to the upload guide only once there is a file", async () => {
    server.reply(DETAIL, detail({ export: ready, findings: [], finding_groups: [] }));
    server.reply(`${DETAIL}/exports`, { status: 202, body: { job_id: "job-1" } });
    server.reply(`${DETAIL}/exports/job-1`, fileOut());
    open();
    expect(await screen.findByRole("button", { name: "Make my GSTR-1 file" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Open the upload guide" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Make my GSTR-1 file" }));
    expect(await screen.findByRole("link", { name: "Open the upload guide" })).toHaveAttribute("href", `/b/b-1/filing/${INST}/portal-guide`);
    // The step strip and the tab say a file was made; making it again is no longer the blue button.
    expect(screen.getByRole("tab", { name: /File and lock/ })).toHaveTextContent("File made");
    expect(screen.getByRole("button", { name: "Make the file again" })).toHaveClass("btn-secondary");
  });

  it("says a file has been checked only when the server says so", async () => {
    server.reply(DETAIL, detail({ export: ready, findings: [], finding_groups: [] }));
    server.reply(`${DETAIL}/exports`, { status: 202, body: { job_id: "job-1" } });
    server.reply(`${DETAIL}/exports/job-1`, fileOut({ portal_tested: true, ready_to_upload: true }));
    open();
    fireEvent.click(await screen.findByRole("button", { name: "Make my GSTR-1 file" }));
    expect(await screen.findByText(/has been checked against the GST portal/)).toBeInTheDocument();
  });

  it("shows plain words when the file could not be made, and when the plan does not allow it", async () => {
    server.reply(DETAIL, detail({ export: ready, findings: [], finding_groups: [] }));
    server.reply(`${DETAIL}/exports`, { status: 202, body: { job_id: "job-1" } }, { status: 409, body: { error: { code: "download_not_available", message: "x" } } });
    server.reply(`${DETAIL}/exports/job-1`, { status: 200, body: { status: "failed", error_code: "changed_during_export", files: [], not_in_file: [], unverified_tables: [], portal_tested: false, ready_to_upload: false } });
    open();
    fireEvent.click(await screen.findByRole("button", { name: "Make my GSTR-1 file" }));
    expect(await screen.findByText(/The return changed while the file was being made/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Make my GSTR-1 file" }));
    expect(await screen.findByText("Downloading the file is not available on your plan yet.")).toBeInTheDocument();
  });
});

describe("Marking filed", () => {
  const form = () => ({ date: screen.getByLabelText("Date you filed it"), arn: screen.getByLabelText("ARN from the portal") });

  it("records the date and ARN and shows the return as filed", async () => {
    server.reply(DETAIL, detail({ export: ready }), detail({ export: ready }, { status: "filed_locked", filed_on: "2026-11-10", arn: "AA1911260000001" }));
    server.reply(`${DETAIL}/filed`, { status: 200, body: { status: "filed_locked", filed_on: "2026-11-10", arn: "AA1911260000001", snapshot_version: 2, changed_since_export: false, has_file: true } });
    open();
    await screen.findByText(/Draft: not filed/);
    const submit = screen.getByRole("button", { name: "Mark as filed and lock" });
    expect(submit).toBeDisabled();
    fireEvent.change(form().date, { target: { value: "2026-11-10" } });
    fireEvent.change(form().arn, { target: { value: " AA1911260000001 " } });
    fireEvent.click(submit);
    await waitFor(() => expect(sentTo(`${DETAIL}/filed`)).toHaveLength(1));
    expect(sentTo(`${DETAIL}/filed`)[0].body).toEqual({ filed_on: "2026-11-10", arn: "AA1911260000001", accept_changed: null });
    expect(await screen.findByText("AA1911260000001")).toBeInTheDocument();
    expect(screen.getByText("10-Nov-2026")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Make my GSTR-1 file" })).toBeNull();
  });

  it("shows what differs by document number and locks only with a reason", async () => {
    server.reply(DETAIL, detail({ export: ready }), detail({ export: ready }, { status: "filed_locked", filed_on: "2026-11-10", arn: "A1" }));
    server.reply(`${DETAIL}/filed`, { status: 409, body: { error: { code: "changed_since_export", message: "x" } } }, { status: 200, body: { status: "filed_locked", filed_on: "2026-11-10", arn: "A1", snapshot_version: 2, changed_since_export: true, has_file: true } });
    server.reply(`${DETAIL}/changes`, { status: 200, body: { reference: { purpose: "export", version: 1 }, same: false, difference: { added: [{ section: "b2b", number: "INV-2" }], removed: [], changed: [{ section: "cdnr", number: "CN-1" }], summaries: ["b2cs"] } } });
    open();
    await screen.findByText(/Draft: not filed/);
    fireEvent.change(form().date, { target: { value: "2026-11-10" } });
    fireEvent.change(form().arn, { target: { value: "A1" } });
    fireEvent.click(screen.getByRole("button", { name: "Mark as filed and lock" }));
    expect(await screen.findByText(/INV-2 \(business sales\)/)).toBeInTheDocument();
    expect(screen.getByText(/CN-1 \(credit notes to businesses\)/)).toBeInTheDocument();
    expect(screen.getByText(/other consumer sales/)).toBeInTheDocument();
    const lockButton = screen.getByRole("button", { name: "Lock with this reason" });
    expect(lockButton).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Why is what you filed different?"), { target: { value: "Filed INV-2 by hand" } });
    fireEvent.click(lockButton);
    await waitFor(() => expect(sentTo(`${DETAIL}/filed`)).toHaveLength(2));
    expect(sentTo(`${DETAIL}/filed`)[1].body).toEqual({ filed_on: "2026-11-10", arn: "A1", accept_changed: { reason: "Filed INV-2 by hand" } });
  });

  it("keeps asking for the reason after a later try is refused for another cause", async () => {
    server.reply(DETAIL, detail({ export: ready }));
    server.reply(`${DETAIL}/filed`,
      { status: 409, body: { error: { code: "changed_since_export", message: "x" } } },
      { status: 422, body: { error: { code: "arn_invalid", message: "x", field: "arn" } } });
    server.reply(`${DETAIL}/changes`, { status: 200, body: { reference: { purpose: "export", version: 1 }, same: false, difference: { added: [{ section: "b2b", number: "INV-2" }], removed: [], changed: [], summaries: [] } } });
    open();
    await screen.findByText(/Draft: not filed/);
    fireEvent.change(form().date, { target: { value: "2026-11-10" } });
    fireEvent.change(form().arn, { target: { value: "A1" } });
    fireEvent.click(screen.getByRole("button", { name: "Mark as filed and lock" }));
    const why = await screen.findByLabelText("Why is what you filed different?");
    fireEvent.change(why, { target: { value: "Filed INV-2 by hand" } });
    fireEvent.click(screen.getByRole("button", { name: "Lock with this reason" }));
    await waitFor(() => expect(sentTo(`${DETAIL}/filed`)).toHaveLength(2));
    await waitFor(() => expect(screen.getByRole("button", { name: "Lock with this reason" })).not.toBeDisabled());
    expect(screen.getByLabelText("Why is what you filed different?")).toHaveValue("Filed INV-2 by hand");
  });

  it("shows a refused date or ARN under its field", async () => {
    server.reply(DETAIL, detail({ export: ready }));
    server.reply(`${DETAIL}/filed`, { status: 422, body: { error: { code: "filed_on_before_period", message: "x", field: "filed_on" } } });
    open();
    await screen.findByText(/Draft: not filed/);
    fireEvent.change(form().date, { target: { value: "2026-10-30" } });
    fireEvent.change(form().arn, { target: { value: "A1" } });
    fireEvent.click(screen.getByRole("button", { name: "Mark as filed and lock" }));
    expect(await screen.findByText("The filing date can't be before the period ends.")).toBeInTheDocument();
  });

  it("lets the CA record a filing too", async () => {
    server.reply(DETAIL, detail({ export: ready }));
    open("ca");
    expect(await screen.findByRole("button", { name: "Mark as filed and lock" })).toBeInTheDocument();
  });
});

describe("A locked return", () => {
  const locked = () => detail({ export: ready, draft: false, banner: null }, { status: "filed_locked", filed_on: "2026-11-10", arn: "AA1911260000001" });

  it("shows when it was filed, downloads the file kept with the lock, and lets only the owner unlock it", async () => {
    server.reply(DETAIL, locked(), detail({ export: ready }, { status: "unlocked" }));
    server.reply(`${DETAIL}/lock-file`, fileOut({ version: 2 }));
    server.reply(`${DETAIL}/unlock`, { status: 200, body: { status: "unlocked" } });
    open();
    expect(await screen.findByText("AA1911260000001")).toBeInTheDocument();
    expect(screen.getAllByText("Filed and locked").length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Make my GSTR-1 file" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Download the file we kept" }));
    expect(await screen.findByRole("link", { name: "Download the file" })).toHaveAttribute("href", "https://files.example/part1");
    fireEvent.click(screen.getByRole("button", { name: "Unlock this return" }));
    const unlock = within(screen.getByLabelText("Why are you unlocking this return?").closest("form")!).getByRole("button", { name: "Unlock this return" });
    expect(unlock).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Why are you unlocking this return?"), { target: { value: "The portal asked us to file again" } });
    fireEvent.click(unlock);
    await waitFor(() => expect(sentTo(`${DETAIL}/unlock`)).toHaveLength(1));
    expect(sentTo(`${DETAIL}/unlock`)[0].body).toEqual({ reason: "The portal asked us to file again" });
    expect(await screen.findByText(/This return was unlocked/)).toBeInTheDocument();
  });

  it("offers no unlock to an admin or the CA", async () => {
    for (const role of ["admin", "ca"]) {
      resetSessionForTests();
      server = fakeApi();
      server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
      server.reply(DETAIL, locked());
      server.reply("/api/v1/me/businesses", mine(role));
      window.history.replaceState(null, "", `/b/b-1/filing/${INST}?tab=file`);
      const view = render(<App />);
      await screen.findByText("AA1911260000001");
      expect(screen.queryByRole("button", { name: "Unlock this return" })).toBeNull();
      expect(screen.getByRole("button", { name: "Download the file we kept" })).toBeInTheDocument();
      view.unmount();
    }
  });
});

describe("The plan beside the file (R1-M9)", () => {
  const PLAN = "/api/v1/b/b-1/plan";
  const plan = (free: boolean) => ({ status: 200, body: { name: "GST filing", monthly_rupees: 499, quarterly_rupees: 1499, gst_note: "plus 18% GST on our fee", free_for_now: free } });

  it("shows the prices and says free for now when the server says so", async () => {
    server.reply(DETAIL, detail({ export: ready }));
    server.reply(PLAN, plan(true));
    open();
    expect(await screen.findByText(/₹499 a month, or ₹1,499 a quarter, plus 18% GST on our fee/)).toBeInTheDocument();
    expect(screen.getByText(/free for now/)).toBeInTheDocument();
  });

  it("does not say free once the server stops saying it", async () => {
    server.reply(DETAIL, detail({ export: ready }));
    server.reply(PLAN, plan(false));
    open();
    await screen.findByText(/₹499 a month/);
    expect(screen.queryByText(/free for now/)).toBeNull();
  });
});
