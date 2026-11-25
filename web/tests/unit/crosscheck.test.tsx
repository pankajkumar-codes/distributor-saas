import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { fakeApi } from "./fakeApi";

const REFRESH = "/api/v1/auth/refresh";
const ME = "/api/v1/me/businesses";
const CHANNELS = "/api/v1/b/b-1/channels";
const CROSS = "/api/v1/b/b-1/own-invoices/crosscheck";
const me = (role: string) => ({ status: 200, body: { businesses: [{ business_id: "b-1", display_name: "Vaashi Essentials", gstin: null, role }] } });
const side = { live: true, documents: 26, unplaced_rows: 0 };
const ref = (n: string) => ({ seller_gstin: "19ABCDE1234F1Z5", doc_type: "invoice", doc_number: n });
const cross = (over: Record<string, unknown> = {}) => ({
  status: 200,
  body: {
    show_validate_note: false,
    compared: true,
    excel: side,
    pdf: side,
    matching: 22,
    only_in_excel: [ref("INV-0419")],
    only_in_pdf: [ref("INV-0430")],
    mismatches: [
      { document: ref("INV-0412"), differences: [{ field: "taxable_value", excel: "12500.00", pdf: "12000.00" }, { field: "doc_date", excel: "2026-10-03", pdf: "2026-10-04" }], excel_row_ids: [], pdf_row_ids: [] },
    ],
    not_compared: [],
    ...over,
  },
});

let server: ReturnType<typeof fakeApi>;
beforeEach(() => {
  resetSessionForTests();
  server = fakeApi();
  server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
  server.reply(CHANNELS, { status: 200, body: { amazon: false, flipkart: false, meesho: false, own_invoices: true, answered: true } });
});
afterEach(() => vi.unstubAllGlobals());

function open(path: string, role = "owner") {
  server.reply(ME, me(role));
  window.history.replaceState(null, "", path);
  render(<App />);
}

describe("own invoices cross-check", () => {
  it("lists each difference with both values as the server sent them, and offers no way to pick a side", async () => {
    server.reply(CROSS, cross());
    open("/b/b-1/uploads/crosscheck");
    expect(await screen.findByRole("heading", { level: 1, name: "Your PDFs and your Excel sheet" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { level: 2, name: "PDF and Excel don't match everywhere" })).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(within(table).getByText("INV-0412")).toBeInTheDocument();
    expect(within(table).getByText("₹12,000.00")).toBeInTheDocument(); // PDF
    expect(within(table).getByText("₹12,500.00")).toBeInTheDocument(); // Excel
    expect(within(table).getByText("04-Oct-2026")).toBeInTheDocument();
    expect(screen.getByText(/INV-0419/)).toBeInTheDocument();
    expect(screen.getByText(/INV-0430/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Use (PDF|Excel)/ })).toBeNull();
    expect(screen.getByText(/never say which side is right/)).toBeInTheDocument();
  });

  it("says the check has not run when only one side is uploaded, with the validate note", async () => {
    server.reply(CROSS, cross({ compared: false, show_validate_note: true, mismatches: [], only_in_excel: [], only_in_pdf: [] }));
    open("/b/b-1/uploads/crosscheck");
    expect(await screen.findByText(/runs when you have uploaded both/)).toBeInTheDocument();
    expect(screen.getByText(/we can validate your Excel sheet/)).toBeInTheDocument();
  });

  it("shows the Uploads banner with a link to the cross-check", async () => {
    server.reply(CROSS, cross());
    server.reply("/api/v1/b/b-1/uploads", { status: 200, body: { uploads: [] } });
    open("/b/b-1/uploads");
    const link = await screen.findByRole("link", { name: "Review the differences" });
    expect(link).toHaveAttribute("href", "/b/b-1/uploads/crosscheck");
  });

  it("is not there for a role that cannot view uploads, and asks the server for nothing", async () => {
    open("/b/b-1/uploads/crosscheck", "billing");
    expect(await screen.findByText(/You don't have access to this page/i)).toBeInTheDocument();
    expect(server.sent.filter((s) => s.path === CROSS)).toHaveLength(0);
  });
});
