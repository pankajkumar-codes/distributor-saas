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
    const other = (await screen.findByText("(5) All other ITC")).closest("tr") as HTMLElement;
    const central = within(other).getByLabelText("Central Tax (State/UT Tax is the same), (5) All other ITC");
    expect(central).toHaveValue("100.00");
    expect(within(other).queryByLabelText(/^State\/UT Tax/)).toBeNull();
    expect(within(other).getByText("Same as Central")).toBeInTheDocument();
    fireEvent.change(central, { target: { value: "250.50" } });
    fireEvent.click(screen.getByRole("button", { name: "Save what I entered" }));
    await waitFor(() => expect(sentTo(`${WS}/entries`, "PUT")).toHaveLength(1));
    expect(sentTo(`${WS}/entries`, "PUT")[0].body).toEqual({ entries: { "t4a.other.cgst": "250.50" }, based_on_seq: 3 });
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
  });

  it("keeps what was typed and says so when someone else has saved, and a second save still goes against the old save", async () => {
    server.reply(WS, sheet({ entries: { "t4a.other.cgst": "100.00", "t4a.other.sgst": "100.00" }, entries_seq: 3 }), sheet({ entries: { "t4a.other.cgst": "999.00", "t4a.other.sgst": "999.00" }, entries_seq: 4 }));
    server.reply(`${WS}/entries`, { status: 409, body: { error: { code: "worksheet_changed", message: "Changed." } } }, { status: 409, body: { error: { code: "worksheet_changed", message: "Changed." } } });
    open();
    const other = (await screen.findByText("(5) All other ITC")).closest("tr") as HTMLElement;
    const box = "Central Tax (State/UT Tax is the same), (5) All other ITC";
    fireEvent.change(within(other).getByLabelText(box), { target: { value: "250.50" } });
    fireEvent.click(screen.getByRole("button", { name: "Save what I entered" }));
    expect(await screen.findByText(/Someone else saved this worksheet while you were typing/)).toBeInTheDocument();
    await waitFor(() => expect(sentTo(WS, "GET")).toHaveLength(2)); // the refetch has happened
    expect(within(other).getByLabelText(box)).toHaveValue("250.50"); // not replaced
    expect(screen.getByText(/Someone else saved this worksheet/)).toBeInTheDocument(); // not cleared by the refetch
    fireEvent.click(screen.getByRole("button", { name: "Save what I entered" }));
    await waitFor(() => expect(sentTo(`${WS}/entries`, "PUT")).toHaveLength(2));
    expect(sentTo(`${WS}/entries`, "PUT")[1].body).toEqual({ entries: { "t4a.other.cgst": "250.50" }, based_on_seq: 3 }); // still the old save
    fireEvent.click(await screen.findByRole("button", { name: "Show what was saved instead" }));
    expect(within(other).getByLabelText(box)).toHaveValue("999.00");
    expect(screen.queryByText(/Someone else saved this worksheet/)).toBeNull();
  });

  it("downloads the Excel file from a fresh link once it is built", async () => {
    server.reply(WS, sheet());
    server.reply(`${WS}/excel`, { status: 200, body: { url: "https://files.example/w.xlsx", name: "w.xlsx", version: 2, entries_seq: null, out_of_date: false } });
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    open();
    fireEvent.click(await screen.findByRole("button", { name: "Download as Excel" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://files.example/w.xlsx"));
  });

  it("makes the PDF in the background: queued, then a link, and links to the portal guide", async () => {
    server.reply(WS, sheet());
    server.reply(`POST ${WS}/pdf`, { status: 202, body: { job_id: "job-1" } });
    server.reply(`${WS}/pdf/job-1`, { status: 200, body: { status: "queued" } }, { status: 200, body: { status: "ready", url: "https://files.example/w.pdf" } });
    open();
    expect(await screen.findByRole("link", { name: "How to enter this on the GST portal" })).toHaveAttribute("href", `/b/b-1/filing/${INST}/portal-guide-3b`);
    fireEvent.click(await screen.findByRole("button", { name: "Make a PDF" }));
    expect(await screen.findByRole("button", { name: "Making the PDF…" })).toBeDisabled();
    expect(await screen.findByRole("link", { name: "Download the PDF" }, { timeout: 4000 })).toHaveAttribute("href", "https://files.example/w.pdf");
  });

  it("says so when the PDF could not be made", async () => {
    server.reply(WS, sheet());
    server.reply(`POST ${WS}/pdf`, { status: 202, body: { job_id: "job-2" } });
    server.reply(`${WS}/pdf/job-2`, { status: 200, body: { status: "failed", error_code: "render_failed" } });
    open();
    fireEvent.click(await screen.findByRole("button", { name: "Make a PDF" }));
    expect(await screen.findByText(/We couldn't make the PDF/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Make a PDF" })).toBeEnabled();
  });

  it("stops asking and lets the person try again when the PDF status fails after a queued answer", async () => {
    server.reply(WS, sheet());
    server.reply(`POST ${WS}/pdf`, { status: 202, body: { job_id: "job-3" } });
    server.reply(`${WS}/pdf/job-3`, { status: 200, body: { status: "queued" } }, { status: 500 });
    open();
    fireEvent.click(await screen.findByRole("button", { name: "Make a PDF" }));
    expect(await screen.findByText(/We couldn't make the PDF/, undefined, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Make a PDF" })).toBeEnabled();
    const asked = sentTo(`${WS}/pdf/job-3`, "GET").length;
    expect(asked).toBe(2);
    await new Promise((r) => setTimeout(r, 3300)); // two more intervals would have passed
    expect(sentTo(`${WS}/pdf/job-3`, "GET")).toHaveLength(asked);
  }, 15000);

  it("shows the server's words when the PDF cannot be started", async () => {
    server.reply(WS, sheet());
    server.reply(`POST ${WS}/pdf`, { status: 409, body: { error: { code: "worksheet_not_available", message: "x", fix: "Your plan does not include this yet." } } });
    open();
    fireEvent.click(await screen.findByRole("button", { name: "Make a PDF" }));
    expect(await screen.findByText(/Your plan does not include this yet/)).toBeInTheDocument();
  });

  it("offers no Excel download before the worksheet is built", async () => {
    server.reply(WS, sheet({ built: false, outward: null }));
    open();
    await screen.findByRole("button", { name: "Build the worksheet" });
    expect(screen.queryByRole("button", { name: "Download as Excel" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Make a PDF" })).toBeNull();
  });

  it("keeps the boxes of every tab when the person moves between tabs, and saves them all at once", async () => {
    server.reply(WS, sheet({ entries_seq: 1 }));
    server.reply(`${WS}/entries`, { status: 200, body: { entries: {}, entries_seq: 2, net_itc: {} } });
    open();
    fireEvent.click(await screen.findByRole("tab", { name: "4(A) Credit" }));
    fireEvent.change(screen.getByLabelText("Integrated Tax, (5) All other ITC"), { target: { value: "21600.00" } });
    fireEvent.click(screen.getByRole("tab", { name: "5 Exempt and interest" }));
    expect(screen.getByLabelText("Integrated Tax, (5) All other ITC")).not.toBeVisible(); // hidden with its tab, still holding what was typed
    fireEvent.change(screen.getByLabelText("Integrated Tax, Interest"), { target: { value: "12.00" } });
    fireEvent.click(screen.getByRole("tab", { name: "4(A) Credit" }));
    expect(screen.getByLabelText("Integrated Tax, (5) All other ITC")).toHaveValue("21600.00");
    fireEvent.click(screen.getByRole("button", { name: "Save what I entered" }));
    await waitFor(() => expect(sentTo(`${WS}/entries`, "PUT")).toHaveLength(1));
    expect(sentTo(`${WS}/entries`, "PUT")[0].body).toEqual({ entries: { "t4a.other.igst": "21600.00", "t5_1.interest.igst": "12.00" }, based_on_seq: 1 });
  });

  it("puts the server's words under the box it names", async () => {
    server.reply(WS, sheet());
    server.reply(`${WS}/entries`, { status: 422, body: { error: { code: "entry_invalid", message: "x", field: "t4b.rev_other.igst", fix: "An amount cannot be negative." } } });
    open();
    const rev = (await screen.findByText("(2) Others")).closest("tr") as HTMLElement;
    const box = within(rev).getByLabelText("Integrated Tax, (2) Others");
    fireEvent.change(box, { target: { value: "-5" } });
    fireEvent.click(screen.getByRole("button", { name: "Save what I entered" }));
    expect((await within(rev).findAllByText("An amount cannot be negative.")).length).toBeGreaterThan(0);
    expect(box).toHaveAttribute("aria-invalid", "true");
  });

  it("opens the tab that holds a refused box and names it, when the save is made from another tab", async () => {
    server.reply(WS, sheet());
    server.reply(`${WS}/entries`, { status: 422, body: { error: { code: "entry_invalid", message: "x", field: "t4a.other.igst", fix: "An amount cannot be negative." } } });
    open();
    fireEvent.click(await screen.findByRole("tab", { name: "4(A) Credit" }));
    const box = screen.getByLabelText("Integrated Tax, (5) All other ITC");
    fireEvent.change(box, { target: { value: "-5" } });
    fireEvent.click(screen.getByRole("tab", { name: "3.1 Outward" }));
    expect(box).not.toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Save what I entered" }));
    await waitFor(() => expect(screen.getByRole("tab", { name: "4(A) Credit" })).toHaveAttribute("aria-selected", "true"));
    expect(box).toBeVisible();
    expect(box).toHaveAttribute("aria-invalid", "true");
    const row = box.closest("tr") as HTMLElement;
    expect(within(row).getAllByText("An amount cannot be negative.").length).toBeGreaterThan(0);
    expect(screen.getByText(/Some amounts need a change in 4\(A\) Credit/)).toBeInTheDocument();
  });

  it("is a not-found page for billing, which the server refuses", async () => {
    open("billing");
    expect(await screen.findByText("You don't have access to this page")).toBeInTheDocument();
    expect(sentTo(WS, "GET")).toHaveLength(0);
  });
});
