import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { GUIDE_STEPS } from "../../src/screens/filing/PortalGuide";
import { fakeApi } from "./fakeApi";

// The GSTR-1 upload guide (mocks v16 "Portal guides"): its own page in three tabs, so it fits one laptop screen.
const REFRESH = "/api/v1/auth/refresh";
const ME = "/api/v1/me/businesses";
const LIST = "/api/v1/b/b-1/returns";
const G1 = "11111111-1111-4111-8111-111111111111";
const G3 = "33333333-3333-4333-8333-333333333333";
const me = (role = "owner") => ({ status: 200, body: { businesses: [{ business_id: "b-1", display_name: "Vaashi Essentials", gstin: "19ABCDE1234F1Z5", role }] } });
const row = (id: string, form: string) => ({
  instance_id: id, form, period: "2026-10", period_label: "October 2026", period_start: "2026-10-01", period_end: "2026-10-31",
  due_date: null, due_date_confirmed: false, due_date_source_url: null, status: "open",
});
const list = (...returns: unknown[]) => ({ status: 200, body: { fy: "2026-27", filing_frequency: "monthly", returns } });

let server: ReturnType<typeof fakeApi>;
beforeEach(() => {
  resetSessionForTests();
  server = fakeApi();
  server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
});
afterEach(() => vi.unstubAllGlobals());

function open(id: string, role = "owner") {
  server.reply(ME, me(role));
  window.history.replaceState(null, "", `/b/b-1/filing/${id}/portal-guide`);
  render(<App />);
}

describe("GSTR-1 portal guide", () => {
  it("shows every step across its tabs, with the steps nobody has looked at on the live portal marked", async () => {
    server.reply(LIST, list(row(G1, "GSTR1"), row(G3, "GSTR3B")));
    open(G1);
    expect(await screen.findByRole("heading", { level: 1, name: "Upload GSTR-1 on the GST portal" })).toBeTruthy();
    expect(screen.getByText(/We have not checked them against the live portal yet/)).toBeTruthy();
    const seen: string[] = [];
    for (const tab of screen.getAllByRole("tab")) {
      fireEvent.click(tab);
      const panel = screen.getByRole("tabpanel");
      seen.push(...within(panel).getAllByRole("listitem").map((li) => li.textContent ?? ""));
    }
    const steps = GUIDE_STEPS("October 2026");
    expect(seen).toHaveLength(steps.length);
    steps.forEach((s, i) => expect(seen[i]).toContain(s.text));
    expect(seen.filter((t) => t.includes("Not checked")).length).toBe(steps.filter((s) => s.check).length);
    expect(seen.join(" ")).toMatch(/Prepare offline/);
    expect(seen.join(" ")).toMatch(/Uploading the file does not file the return/);
    expect(seen.join(" ")).toMatch(/the financial year and the period "October 2026"/);
    expect(screen.getByRole("link", { name: "GSTR-3B entry" })).toHaveAttribute("href", `/b/b-1/filing/${G3}/portal-guide-3b`);
    expect(screen.getByRole("link", { name: "Back to GSTR-1" })).toHaveAttribute("href", `/b/b-1/filing/${G1}?tab=file`);
  });

  it("is a not-found page for a GSTR-3B", async () => {
    server.reply(LIST, list(row(G3, "GSTR3B")));
    open(G3);
    expect(await screen.findByRole("heading", { name: "We couldn't find that page" })).toBeTruthy();
  });

  it("turns away a billing member", async () => {
    server.reply(LIST, list(row(G1, "GSTR1")));
    open(G1, "billing");
    expect(await screen.findByRole("heading", { name: "You don't have access to this page" })).toBeTruthy();
  });
});
