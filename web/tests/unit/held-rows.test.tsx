import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { fakeApi } from "./fakeApi";

const REFRESH = "/api/v1/auth/refresh";
const ME = "/api/v1/me/businesses";
const STATES = "/api/v1/refdata/state-codes";
const RUN = "/api/v1/b/b-1/runs/r-1";
const ROWS = "/api/v1/b/b-1/runs/r-1/rows";
const resolve = (id: string) => `/api/v1/b/b-1/rows/${id}/resolve`;
const me = (role: string) => ({ status: 200, body: { businesses: [{ business_id: "b-1", display_name: "Vaashi Essentials", gstin: null, role }] } });
const run = (over: Record<string, unknown> = {}) => ({ status: 200, body: { id: "r-1", status: "staged", counts: { held: 2 }, held_by_reason: { bill_ship_diff: 2 }, ...over } });
const PICK = { action: "pick_state", label: "Pick the state", effect_note: "The row uses the state you pick." };
const ASIDE = { action: "set_aside", label: "Leave this row out", effect_note: "This cannot be undone." };
const row = (n: number, over: Record<string, unknown> = {}) => ({
  row_id: `row-${n}`,
  run_id: "r-1",
  file_name: "b2b-oct.csv",
  row_number: n,
  status: "held",
  hold_reason: "bill_ship_diff",
  reason_label: "Bill-to and ship-to states differ",
  values: { invoice_number: `AMZ-${n}`, ship_to_state: "West Bengal", buyer_gstin: "27ABCDE1234F1Z5", taxable_value: "1000.00" },
  errors: [],
  needs_ca_check: true,
  ca_check_note: "Which state applies needs a CA check.",
  allowed_actions: [ASIDE, PICK],
  resolution: null,
  ...over,
});
const rows = (list: unknown[], has_more = false) => ({ status: 200, body: { rows: list, has_more } });

let server: ReturnType<typeof fakeApi>;
function open(role = "owner", list: unknown[] = [row(1), row(2)], runReply = run()) {
  resetSessionForTests();
  server = fakeApi();
  server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
  server.reply(ME, me(role));
  server.reply(STATES, { status: 200, body: { on: "2026-11-19", states: [{ code: "19", name: "West Bengal" }, { code: "27", name: "Maharashtra" }] } });
  server.reply(RUN, ...Array.from({ length: 4 }, () => runReply));
  server.reply(ROWS, ...Array.from({ length: 4 }, () => rows(list)));
  window.history.replaceState(null, "", "/b/b-1/uploads/runs/r-1/held");
  render(<App />);
}
afterEach(() => vi.unstubAllGlobals());
beforeEach(() => window.history.replaceState(null, "", "/"));
const sent = (path: string) => server.sent.filter((s) => s.path === path && s.method === "POST");
const decided = (n: number, kind: string, value: string | null, note: string) => ({ status: 200, body: row(n, { resolution: { action: kind, note, at: "2026-11-19T10:00:00Z", value } }) });

describe("held rows screen", () => {
  it("lists rows by reason with the CA note and the server's cells", async () => {
    open();
    expect(await screen.findByRole("heading", { level: 1, name: "Held rows" })).toBeInTheDocument();
    const group = await screen.findByRole("region", { name: "Bill-to and ship-to states differ" });
    expect(within(group).getByText("Row 1 of b2b-oct.csv")).toBeInTheDocument();
    expect(within(group).getByText("AMZ-2")).toBeInTheDocument();
    expect(within(group).getAllByText("Which state applies needs a CA check.")).toHaveLength(2);
    expect(screen.getByText(/Needs a CA check\./)).toBeInTheDocument();
  });

  it("picks a state with a note, sending the state code and an Idempotency-Key", async () => {
    open("owner", [row(1)]);
    server.reply(resolve("row-1"), decided(1, "pick_state", "27", "Sent to the buyer's Pune office"));
    await screen.findByText("Row 1 of b2b-oct.csv");
    fireEvent.click(screen.getByRole("button", { name: "Pick the state" }));
    const form = await screen.findByRole("form", { name: "Pick the state" });
    fireEvent.change(within(form).getByLabelText("Place of supply"), { target: { value: "27" } });
    fireEvent.change(within(form).getByLabelText("Note (why)"), { target: { value: "Sent to the buyer's Pune office" } });
    fireEvent.click(within(form).getByRole("button", { name: "Use this state" }));
    await waitFor(() => expect(sent(resolve("row-1"))).toHaveLength(1));
    expect(sent(resolve("row-1"))[0].body).toEqual({ action: "pick_state", note: "Sent to the buyer's Pune office", value: "27" });
    expect(sent(resolve("row-1"))[0].headers.get("Idempotency-Key")).toBeTruthy();
  });

  it("needs a state and a note before sending anything", async () => {
    open("owner", [row(1)]);
    await screen.findByText("Row 1 of b2b-oct.csv");
    fireEvent.click(screen.getByRole("button", { name: "Pick the state" }));
    const form = await screen.findByRole("form", { name: "Pick the state" });
    fireEvent.click(within(form).getByRole("button", { name: "Use this state" }));
    expect(await within(form).findByText("Choose a state.")).toBeInTheDocument();
    fireEvent.change(within(form).getByLabelText("Place of supply"), { target: { value: "27" } });
    fireEvent.click(within(form).getByRole("button", { name: "Use this state" }));
    expect(await within(form).findByText("Add a note saying why.")).toBeInTheDocument();
    expect(sent(resolve("row-1"))).toHaveLength(0);
  });

  it("asks twice before leaving a row out, and says it cannot be undone", async () => {
    open("owner", [row(1)]);
    server.reply(resolve("row-1"), decided(1, "set_aside", null, "Duplicate"));
    await screen.findByText("Row 1 of b2b-oct.csv");
    fireEvent.click(screen.getByRole("button", { name: "Leave this row out" }));
    const form = await screen.findByRole("form", { name: "Leave this row out" });
    expect(within(form).getByText("This cannot be undone.")).toBeInTheDocument();
    fireEvent.change(within(form).getByLabelText("Note (why)"), { target: { value: "Duplicate" } });
    fireEvent.click(within(form).getByRole("button", { name: "Leave this row out" }));
    expect(sent(resolve("row-1"))).toHaveLength(0);
    fireEvent.click(await within(form).findByRole("button", { name: "Yes, leave it out" }));
    await waitFor(() => expect(sent(resolve("row-1"))).toHaveLength(1));
    expect(sent(resolve("row-1"))[0].body).toEqual({ action: "set_aside", note: "Duplicate" });
  });

  it("shows the server's words when a decision is refused", async () => {
    open("owner", [row(1)]);
    server.reply(resolve("row-1"), { status: 422, body: { error: { code: "state_unknown", message: "Choose a state from the list.", field: "value" } } });
    await screen.findByText("Row 1 of b2b-oct.csv");
    fireEvent.click(screen.getByRole("button", { name: "Pick the state" }));
    const form = await screen.findByRole("form", { name: "Pick the state" });
    fireEvent.change(within(form).getByLabelText("Place of supply"), { target: { value: "27" } });
    fireEvent.change(within(form).getByLabelText("Note (why)"), { target: { value: "x" } });
    fireEvent.click(within(form).getByRole("button", { name: "Use this state" }));
    expect(await within(form).findByText("Choose a state from the list.")).toBeInTheDocument();
  });

  it("picks one state for several rows, one call each, and lists the ones refused", async () => {
    open();
    server.reply(resolve("row-1"), decided(1, "pick_state", "27", "Same buyer"));
    server.reply(resolve("row-2"), { status: 409, body: { error: { code: "run_not_staged", message: "This file's preview has been closed, so its rows can't be changed." } } });
    await screen.findByText("Row 1 of b2b-oct.csv");
    fireEvent.click(await screen.findByRole("button", { name: "Decide several rows" }));
    fireEvent.click(screen.getByRole("button", { name: "Select all 2" }));
    const bulk = await screen.findByRole("form", { name: "Decide the selected rows" });
    fireEvent.change(within(bulk).getByLabelText("Place of supply"), { target: { value: "27" } });
    fireEvent.change(within(bulk).getByLabelText("Note (why)"), { target: { value: "Same buyer" } });
    fireEvent.click(within(bulk).getByRole("button", { name: "Use this state for 2 rows" }));
    await waitFor(() => expect(sent(resolve("row-2"))).toHaveLength(1));
    expect(sent(resolve("row-1"))[0].body).toEqual({ action: "pick_state", note: "Same buyer", value: "27" });
    expect(sent(resolve("row-1"))[0].headers.get("Idempotency-Key")).not.toBe(sent(resolve("row-2"))[0].headers.get("Idempotency-Key"));
    expect(await screen.findByText(/1 row decided\./)).toBeInTheDocument();
    expect(screen.getByText(/Row 2 of b2b-oct.csv: This file's preview has been closed/)).toBeInTheDocument();
  });

  it("asks twice before leaving several rows out", async () => {
    open();
    server.reply(resolve("row-1"), decided(1, "set_aside", null, "Duplicates"));
    server.reply(resolve("row-2"), decided(2, "set_aside", null, "Duplicates"));
    await screen.findByText("Row 1 of b2b-oct.csv");
    fireEvent.click(await screen.findByRole("button", { name: "Decide several rows" }));
    fireEvent.click(screen.getByRole("button", { name: "Select all 2" }));
    const bulk = await screen.findByRole("form", { name: "Decide the selected rows" });
    fireEvent.change(within(bulk).getByLabelText("What to do"), { target: { value: "set_aside" } });
    fireEvent.change(within(bulk).getByLabelText("Note (why)"), { target: { value: "Duplicates" } });
    fireEvent.click(within(bulk).getByRole("button", { name: "Leave 2 rows out" }));
    expect(sent(resolve("row-1"))).toHaveLength(0);
    fireEvent.click(await within(bulk).findByRole("button", { name: "Yes, leave 2 rows out" }));
    await waitFor(() => expect(sent(resolve("row-2"))).toHaveLength(1));
    expect(sent(resolve("row-1"))[0].body).toEqual({ action: "set_aside", note: "Duplicates" });
  });

  it("names the reasons of selected rows that are on another tab or page (#419)", async () => {
    const hsn = { action: "enter_hsn", label: "Enter the HSN", effect_note: "The row uses the HSN." };
    open("owner", [row(1), row(2), row(3), row(4, { hold_reason: "hsn_missing", reason_label: "HSN missing", allowed_actions: [ASIDE, hsn] })]);
    fireEvent.click(await screen.findByRole("button", { name: "Decide several rows" }));
    fireEvent.click(screen.getByRole("button", { name: "Select all 4" }));
    const bulk = await screen.findByRole("form", { name: "Decide the selected rows" });
    // Rows 1 and 2 are on screen (first tab, first page); row 3 is on page 2 and row 4 on the HSN tab.
    expect(within(bulk).getByText(/2 selected rows are not on screen: Bill-to and ship-to states differ \(1\), HSN missing \(1\)\./)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(within(bulk).getByText(/3 selected rows are not on screen: Bill-to and ship-to states differ \(2\), HSN missing \(1\)\./)).toBeInTheDocument(); // page 2 shows only row 3
  });

  it("clears the selection when bulk mode closes (#419)", async () => {
    open();
    const toggle = await screen.findByRole("button", { name: "Decide several rows" });
    fireEvent.click(toggle);
    fireEvent.click(screen.getByRole("button", { name: "Select all 2" }));
    expect(screen.getByText("2 selected")).toBeInTheDocument();
    fireEvent.click(toggle);
    expect(screen.queryByRole("region", { name: "Decide several rows" })).toBeNull();
    fireEvent.click(toggle);
    expect(screen.getByText("0 selected")).toBeInTheDocument();
    expect(screen.getByLabelText("Select Row 1 of b2b-oct.csv")).not.toBeChecked();
  });

  it("shows a decided row as decided, with its note, and offers nothing more", async () => {
    open("owner", [row(1, { resolution: { action: "pick_state", note: "Pune office", at: "2026-11-19T10:00:00Z", value: "27" } })]);
    expect(await screen.findByText(/State picked/)).toBeInTheDocument();
    expect(screen.getByText("Your note: Pune office")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pick the state" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Select all/ })).toBeNull();
  });

  it("lets a CA read the rows but not decide them", async () => {
    open("ca");
    expect(await screen.findByText("Only an owner or admin can decide these rows.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pick the state" })).toBeNull();
  });

  it("says so when the file's preview is closed", async () => {
    open("owner", [row(1)], run({ status: "confirmed" }));
    expect(await screen.findByText("This file's preview is closed, so its rows can't be changed.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pick the state" })).toBeNull();
  });

  it("says nothing is held when there are no rows", async () => {
    open("owner", []);
    expect(await screen.findByText("No rows are held. Nothing to decide.")).toBeInTheDocument();
  });

  it("offers Show more rows when the server has more", async () => {
    resetSessionForTests();
    server = fakeApi();
    server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
    server.reply(ME, me("owner"));
    server.reply(STATES, { status: 200, body: { on: "2026-11-19", states: [] } });
    server.reply(RUN, run());
    server.reply(ROWS, rows([row(1)], true), rows([row(2)]));
    window.history.replaceState(null, "", "/b/b-1/uploads/runs/r-1/held");
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Show more rows" }));
    expect(await screen.findByText("Row 2 of b2b-oct.csv")).toBeInTheDocument();
    expect(server.sent.filter((s) => s.path === ROWS)[1].url).toContain("offset=50");
  });

  it("says when the rows cannot be loaded, with Try again", async () => {
    resetSessionForTests();
    server = fakeApi();
    server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
    server.reply(ME, me("owner"));
    server.reply(STATES, { status: 200, body: { on: "2026-11-19", states: [] } });
    window.history.replaceState(null, "", "/b/b-1/uploads/runs/r-1/held");
    render(<App />);
    expect(await screen.findByText(/We couldn't load these rows/, undefined, { timeout: 15000 })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  }, 20000);

  it("shows not found for a run in another business", async () => {
    resetSessionForTests();
    server = fakeApi();
    server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
    server.reply(ME, me("owner"));
    server.reply(STATES, { status: 200, body: { on: "2026-11-19", states: [] } });
    server.reply(RUN, { status: 404, body: { error: { code: "not_found", message: "Not found" } } });
    server.reply(ROWS, { status: 404, body: { error: { code: "not_found", message: "Not found" } } });
    window.history.replaceState(null, "", "/b/b-1/uploads/runs/r-1/held");
    render(<App />);
    expect(await screen.findByText(/couldn't find that page/i)).toBeInTheDocument();
  });

  it("gives a billing user no access", async () => {
    open("billing");
    expect(await screen.findByText(/don't have access/i)).toBeInTheDocument();
  });
});

describe("link from the upload page", () => {
  it("shows the held count and a link to the review screen", async () => {
    resetSessionForTests();
    server = fakeApi();
    server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
    server.reply(ME, me("owner"));
    server.reply("/api/v1/b/b-1/channels", { status: 200, body: { amazon: true, flipkart: false, meesho: false, own_invoices: false, answered: true } });
    const up = { id: "u-1", section: "amazon", file_name: "b2b-oct.csv", size_bytes: 9, status: "parsed", reject_reason: null, reject_message: null, run_id: "r-1", run_ids: ["r-1"], raw_available: true, created_at: "2026-11-02T10:00:00Z" };
    server.reply("/api/v1/b/b-1/uploads", ...Array.from({ length: 4 }, () => ({ status: 200, body: { uploads: [up] } })));
    server.reply(RUN, ...Array.from({ length: 4 }, () => run()));
    window.history.replaceState(null, "", "/b/b-1/uploads");
    render(<App />);
    const link = await screen.findByRole("link", { name: "Review held rows" });
    expect(link).toHaveAttribute("href", "/b/b-1/uploads/runs/r-1/held");
    expect(screen.getByText("2 rows held")).toBeInTheDocument();
  });
});
