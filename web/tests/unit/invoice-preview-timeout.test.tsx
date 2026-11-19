import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { fakeApi } from "./fakeApi";

vi.mock("../../src/features", () => ({ FEATURES: { invoicing: true } })); // R2 screens
vi.mock("../../src/api/useJob", async (orig) => ({ ...(await orig<typeof import("../../src/api/useJob")>()), pollDelay: () => 1 })); // same polling, without the waits

const B = "/api/v1/b/b-1";
const ONE = `${B}/drafts/d-1`;
const draft = {
  id: "d-1", kind: "invoice", version: 1, customer_id: "c-1", cash_buyer: null, bill_to: { name: "Sharma Traders" }, ship_to: null, doc_date: null,
  invoice_discount: "0.00", charges: [], eway: null, customer_collects: false, ship_to_third_party: false, pos_override: null, pos_override_reason: null,
  lines: [{ id: "l-1", line_no: 1, product_id: "p-1", quantity: "10", unit_price: "100.00", discount_kind: null, discount_value: null }],
  total: "1180.00", ready: true, computed_at: "2026-11-09T10:00:00Z", created_at: "2026-11-09T10:00:00Z", updated_at: "2026-11-09T10:00:00Z", computation: null,
}; // fmt: skip
const product = { id: "p-1", name: "Aloe Vera Gel", hsn: "3304", code: "AVG", sale_rate: "120.00", status: "active", version: 1, warnings: [] };

let server: ReturnType<typeof fakeApi>;
beforeEach(() => {
  resetSessionForTests();
  server = fakeApi();
  server.reply("/api/v1/auth/refresh", { status: 200, body: { access_token: "t", expires_in: 3600 } });
  server.reply("/api/v1/me/businesses", { status: 200, body: { businesses: [{ business_id: "b-1", display_name: "Vashi Essentials", gstin: null, role: "owner" }] } });
  server.reply("/api/v1/refdata/state-codes", { status: 200, body: { on: "2026-11-09", states: [] } });
});
afterEach(() => vi.unstubAllGlobals());

describe("a preview that never finishes", () => {
  it("stops polling and says it is taking too long, instead of saying Preparing for ever", async () => {
    server.reply(ONE, { status: 200, body: draft });
    server.reply(`${B}/products/p-1`, { status: 200, body: product });
    server.reply(`${ONE}/preview`, { status: 202, body: { job_id: "j-1", draft_version: 1 } });
    server.reply(`${ONE}/preview/j-1`, ...Array.from({ length: 40 }, () => ({ status: 200, body: { status: "rendering" } })));
    window.history.replaceState(null, "", "/b/b-1/invoices/d-1");
    render(<App />);
    await screen.findByText("Sharma Traders");
    fireEvent.click(screen.getByRole("button", { name: "Preview PDF" }));
    expect(await screen.findByText(/The preview is taking longer than expected/, {}, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.queryByText("Preparing the preview…")).toBeNull();
    const polls = server.sent.filter((s) => s.path === `${ONE}/preview/j-1`).length;
    await new Promise((r) => setTimeout(r, 100));
    expect(server.sent.filter((s) => s.path === `${ONE}/preview/j-1`)).toHaveLength(polls); // no more calls
  });
});
