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
const exp = (over: Record<string, unknown> = {}) => ({
  id: "e-1", kind: "month", period_start: "2026-10-01", period_end: "2026-10-31", sales_lines: 3, purchase_lines: 2, practice_documents: 1,
  created_at: "2026-11-02T10:00:00Z", created: true, due_dates: "Check on the GST portal", gstr1_returns: [{ instance_id: "i-1", form: "GSTR1", period_start: "2026-10-01", period_end: "2026-10-31" }],
  files: [
    { name: "workbook", sha256: "a", size_bytes: 10, url: "https://files.test/w.xlsx" },
    { name: "purchase_register", sha256: "b", size_bytes: 5, url: "https://files.test/r.json" },
  ],
  ...over,
});

let server: ReturnType<typeof fakeApi>;
beforeEach(() => {
  resetSessionForTests();
  server = fakeApi();
  server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
  server.reply(ME, me(), me());
});
afterEach(() => vi.unstubAllGlobals());

const open = () => {
  window.history.replaceState(null, "", "/b/b-1/period-files");
  render(<App />);
};

describe("finished periods", () => {
  it("offers only wholly finished months and quarters, newest first", () => {
    expect(finishedPeriods("month", "2027-01-15", 3).map((p) => p.start)).toEqual(["2026-12-01", "2026-11-01", "2026-10-01"]);
    expect(finishedPeriods("month", "2027-03-01", 2).map((p) => p.label)).toEqual(["Feb 2027", "Jan 2027"]);
    expect(finishedPeriods("quarter", "2027-01-15", 2).map((p) => [p.start, p.label])).toEqual([
      ["2026-10-01", "Oct–Dec 2026"],
      ["2026-07-01", "Jul–Sep 2026"],
    ]);
    expect(finishedPeriods("quarter", "2027-03-31", 1)[0].start).toBe("2026-10-01"); // Q4 is still running
  });
});

describe("monthly and quarterly files", () => {
  it("makes the files for a chosen month and shows a Download link on each", async () => {
    server.reply(`${B}/filing-profile`, filing("monthly"));
    server.reply(`GET ${B}/period-files`, { status: 200, body: { exports: [], has_more: false } });
    open();
    expect(await screen.findByText("None yet.")).toBeInTheDocument();
    expect(screen.queryByLabelText("For")).toBeNull(); // a monthly filer is not offered quarters
    const month = finishedPeriods("month", new Date().toISOString().slice(0, 10), 1)[0];
    fireEvent.change(screen.getByLabelText("Month"), { target: { value: month.start } });
    server.reply(`POST ${B}/period-files`, { status: 200, body: exp() });
    fireEvent.click(screen.getByRole("button", { name: "Make the files" }));
    expect(await screen.findByText("Your files are ready.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Download Excel workbook/ })).toHaveAttribute("href", "https://files.test/w.xlsx");
    expect(screen.getByRole("link", { name: /Download Purchase register/ })).toHaveAttribute("href", "https://files.test/r.json");
    expect(screen.getByRole("link", { name: "open the GSTR1 return" })).toHaveAttribute("href", "/b/b-1/filing/i-1");
    expect(server.sent.find((s) => s.method === "POST" && s.path.endsWith("/period-files"))!.body).toEqual({ kind: "month", start: month.start });
  });

  it("offers quarters to a quarterly filer, and gets fresh links for a file made before", async () => {
    server.reply(`${B}/filing-profile`, filing("quarterly"));
    server.reply(`GET ${B}/period-files`, { status: 200, body: { exports: [exp({ files: [] })], has_more: false } });
    open();
    expect(await screen.findByLabelText("For")).toBeInTheDocument();
    server.reply(`GET ${B}/period-files/e-1`, { status: 200, body: exp({ created: false }) });
    fireEvent.click(await screen.findByRole("button", { name: "Get the files for 2026-10-01 to 2026-10-31" }));
    expect(await screen.findByRole("link", { name: /Download Excel workbook, 2026-10-01/ })).toBeInTheDocument();
  });

  it("shows the server's reason when the download is not available", async () => {
    server.reply(`${B}/filing-profile`, filing("monthly"));
    server.reply(`GET ${B}/period-files`, { status: 200, body: { exports: [], has_more: false } });
    open();
    await screen.findByText("None yet.");
    fireEvent.change(screen.getByLabelText("Month"), { target: { value: finishedPeriods("month", new Date().toISOString().slice(0, 10), 1)[0].start } });
    server.reply(`POST ${B}/period-files`, { status: 409, body: { error: { code: "download_not_available", message: "Downloading the file is not available for your plan yet." } } });
    fireEvent.click(screen.getByRole("button", { name: "Make the files" }));
    expect(await screen.findByText(/not available on your plan yet/)).toBeInTheDocument();
  });

  it("is not there for a role that cannot prepare returns", async () => {
    server = fakeApi();
    server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
    server.reply(ME, me("billing"), me("billing"));
    open();
    expect(await screen.findByText(/You don't have access to this page/)).toBeInTheDocument();
  });
});
