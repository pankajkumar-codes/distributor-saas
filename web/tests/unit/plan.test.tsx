import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { fakeApi } from "./fakeApi";

vi.mock("../../src/features", () => ({ FEATURES: { invoicing: true } })); // R2 screens

const plan = (over: Record<string, unknown> = {}) => ({
  name: "Invoicing and GST", monthly_rupees: 999, quarterly_rupees: 2499, gst_note: "18% GST is extra on our fee.", free_for_now: true,
  free_invoices: 10, used: 3, remaining_free: 7, needs_plan: false, ...over,
});

let server: ReturnType<typeof fakeApi>;
beforeEach(() => {
  resetSessionForTests();
  server = fakeApi();
  server.reply("/api/v1/auth/refresh", { status: 200, body: { access_token: "t", expires_in: 3600 } });
  server.reply("/api/v1/me/businesses", { status: 200, body: { businesses: [{ business_id: "b-1", display_name: "Vashi Essentials", gstin: null, role: "owner" }] } });
});
afterEach(() => vi.unstubAllGlobals());
const open = () => {
  window.history.replaceState(null, "", "/b/b-1/settings/plan");
  render(<App />);
};

describe("invoicing plan", () => {
  it("shows the free-invoice counter and says free for now", async () => {
    server.reply("/api/v1/b/b-1/invoicing-plan", { status: 200, body: plan() });
    open();
    expect(await screen.findByText("3 of 10")).toBeInTheDocument();
    expect(screen.getByText(/7 left/)).toBeInTheDocument();
    expect(screen.getByText("Free for now.")).toBeInTheDocument();
    expect(screen.getByText("Monthly: ₹999.00")).toBeInTheDocument();
    expect(screen.getByText("Quarterly: ₹2,499.00")).toBeInTheDocument();
    expect(screen.getByText("18% GST is extra on our fee.")).toBeInTheDocument();
  });

  it("says when the free invoices are used and a plan is needed", async () => {
    server.reply("/api/v1/b/b-1/invoicing-plan", { status: 200, body: plan({ free_for_now: false, used: 10, remaining_free: 0, needs_plan: true }) });
    open();
    expect(await screen.findByText(/You have used your free invoices/)).toBeInTheDocument();
    expect(screen.queryByText("Free for now.")).toBeNull();
  });
});
