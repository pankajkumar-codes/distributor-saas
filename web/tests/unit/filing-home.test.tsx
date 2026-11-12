import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { fyIst, previousFy } from "../../src/format/dates";
import { fakeApi } from "./fakeApi";

const REFRESH = "/api/v1/auth/refresh";
const ME = "/api/v1/me/businesses";
const NOW = `/api/v1/b/b-1/returns`;
const me = (role = "owner") => ({
  status: 200,
  body: { businesses: [{ business_id: "b-1", display_name: "Vashi Essentials", gstin: "19ABCDE1234F1Z5", role }] },
});
const row = (over: Record<string, unknown>) => ({
  instance_id: crypto.randomUUID(),
  form: "GSTR1",
  period: "2026-Q3",
  period_label: "Oct–Dec 2026",
  period_start: "2026-10-01",
  period_end: "2026-12-31",
  due_date: "2027-01-13",
  due_date_confirmed: true,
  due_date_source_url: null,
  status: "open",
  ...over,
});
const ok = (returns: unknown[], filing_frequency = "quarterly") => ({ status: 200, body: { fy: "x", filing_frequency, returns } });
const NOT_SET = { status: 200, body: { fy: "x", filing_frequency: null, returns: [] } };

let server: ReturnType<typeof fakeApi>;
beforeEach(() => {
  resetSessionForTests();
  server = fakeApi();
  server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
});
afterEach(() => vi.unstubAllGlobals());

function open(role = "owner") {
  server.reply(ME, me(role));
  window.history.replaceState(null, "", "/b/b-1/filing");
  render(<App />);
}

describe("Filing home", () => {
  it("shows the server's rows in order with its labels, only GSTR-1 and GSTR-3B", async () => {
    server.reply(
      NOW,
      ok([
        row({ form: "GSTR1", due_date: "2027-01-13" }),
        row({ form: "GSTR3B", due_date: "2027-01-24", period_label: "Oct–Dec 2026" }),
        row({ form: "IFF", period: "2026-10", period_label: "October 2026" }),
        row({ form: "PMT06", period: "2026-10", period_label: "October 2026" }),
      ]),
      ok([]),
    );
    open();
    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("Oct–Dec 2026");
    expect(rows[0]).toHaveTextContent("01-Oct-2026 to 31-Dec-2026");
    expect(rows[0]).toHaveTextContent("GSTR-1");
    expect(rows[0]).toHaveTextContent("13-Jan-2027");
    expect(rows[1]).toHaveTextContent("GSTR-3B");
    expect(rows[1]).toHaveTextContent("24-Jan-2027");
    expect(screen.getByText("Quarterly (QRMP) filer.")).toBeInTheDocument();
    expect(within(table).queryByRole("button")).toBeNull(); // no filing action until the upload screens exist
    expect(screen.queryByText("To be confirmed")).toBeNull();
  });

  it("marks an unconfirmed date as to be confirmed, with the source link only when it is https", async () => {
    server.reply(
      NOW,
      ok([
        row({ due_date_confirmed: false, due_date_source_url: "https://example.gov/notice" }),
        row({ form: "GSTR3B", due_date_confirmed: false, due_date_source_url: "javascript:alert(1)" }),
        row({ form: "GSTR3B", period: "2026-Q2", period_label: "Jul–Sep 2026", due_date: null, due_date_confirmed: false }),
      ]),
      ok([]),
    );
    open();
    await screen.findByRole("table");
    expect(screen.getAllByText("To be confirmed")).toHaveLength(2);
    const link = screen.getByRole("link", { name: "Where this date comes from" });
    expect(link).toHaveAttribute("href", "https://example.gov/notice");
    expect(screen.getAllByRole("link", { name: "Where this date comes from" })).toHaveLength(1);
    expect(screen.getByText(/No date available/)).toBeInTheDocument();
  });

  it("shows each status in words, and monthly labels as sent", async () => {
    server.reply(
      NOW,
      ok(
        [
          row({ period: "2026-10", period_label: "October 2026", status: "filed_locked" }),
          row({ period: "2026-10", period_label: "October 2026", form: "GSTR3B", status: "unlocked" }),
          row({ period: "2026-09", period_label: "September 2026", status: "skipped" }),
        ],
        "monthly",
      ),
      ok([]),
    );
    open();
    await screen.findByRole("table");
    expect(screen.getByText("Marked as filed")).toBeInTheDocument();
    expect(screen.getByText("Reopened after filing")).toBeInTheDocument();
    expect(screen.getByText("Not required")).toBeInTheDocument();
    expect(screen.getByText("Monthly filer.")).toBeInTheDocument();
    expect(screen.getAllByText("October 2026")).toHaveLength(2);
  });

  it("adds last year's rows only while they are still open", async () => {
    server.reply(NOW, ok([row({ period_label: "Apr–Jun 2026", instance_id: "now" })]), ok([
      row({ period_label: "Jan–Mar 2026", instance_id: "a", status: "open" }),
      row({ period_label: "Oct–Dec 2025", instance_id: "b", status: "filed_locked" }),
    ]));
    open();
    expect(await screen.findByText("Jan–Mar 2026")).toBeInTheDocument();
    expect(screen.queryByText("Oct–Dec 2025")).toBeNull();
    const asked = server.sent.filter((s) => s.path === NOW).map((s) => new URL(s.url).searchParams.get("fy"));
    expect(asked).toEqual([fyIst(), previousFy(fyIst())]);
  });

  it("sends the user to Settings when no frequency is set, and doesn't ask for last year", async () => {
    server.reply(NOW, NOT_SET);
    open();
    const link = await screen.findByRole("link", { name: "Choose your filing frequency" });
    expect(link).toHaveAttribute("href", "/b/b-1/settings/filing");
    expect(server.sent.filter((s) => s.path === NOW)).toHaveLength(1);
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("is NotFound for a business the user isn't in, without asking the server for it", async () => {
    server.reply(ME, me());
    window.history.replaceState(null, "", "/b/b-9/filing");
    render(<App />);
    expect(await screen.findByText(/couldn't find that page/i)).toBeInTheDocument();
    expect(server.paths()).not.toContain("/api/v1/b/b-9/returns");
  });

  it("lets a CA read it (the server decides, and the screen has no actions to hide)", async () => {
    server.reply(NOW, ok([row({})]), ok([]));
    open("ca");
    expect(await screen.findByRole("table")).toBeInTheDocument();
  });
});
