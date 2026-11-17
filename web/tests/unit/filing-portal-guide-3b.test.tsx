import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { GUIDE_3B_NOT_CHECKED, GUIDE_3B_STEPS } from "../../src/screens/filing/Portal3bGuidePage";
import { fakeApi } from "./fakeApi";

const REFRESH = "/api/v1/auth/refresh";
const ME = "/api/v1/me/businesses";
const LIST = "/api/v1/b/b-1/returns";
const G3 = "33333333-3333-4333-8333-333333333333";
const G1 = "11111111-1111-4111-8111-111111111111";
const me = (role = "owner") => ({
  status: 200,
  body: { businesses: [{ business_id: "b-1", display_name: "Vaashi Essentials", gstin: "19ABCDE1234F1Z5", role }] },
});
const row = (id: string, form: string, period_label = "October 2026") => ({
  instance_id: id, form, period: "2026-10", period_label, period_start: "2026-10-01", period_end: "2026-10-31",
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
  window.history.replaceState(null, "", `/b/b-1/filing/${id}/portal-guide-3b`);
  render(<App />);
}

describe("GSTR-3B portal guide", () => {
  it("shows every step for the period, each marked Not checked, and says the person enters it themselves", async () => {
    server.reply(LIST, list(row(G1, "GSTR1"), row(G3, "GSTR3B")));
    open(G3);
    expect(await screen.findByRole("heading", { name: "Enter GSTR-3B on the GST portal" })).toBeTruthy();
    const steps = within(screen.getByRole("list")).getAllByRole("listitem");
    expect(steps).toHaveLength(GUIDE_3B_STEPS("October 2026").length);
    for (const li of steps) expect(within(li).getByText("Not checked").getAttribute("title")).toBe(GUIDE_3B_NOT_CHECKED);
    for (const li of steps) expect(within(li).getByText(GUIDE_3B_NOT_CHECKED)).toBeTruthy();
    expect(screen.getByText(/October 2026/, { selector: "p" }).textContent).toContain("enter and submit it on the GST portal yourself");
    expect(screen.getAllByText(/To be confirmed/).length).toBeGreaterThan(0);
  });

  it("never says a return is filed or ready to file, and shows no payable amount", async () => {
    server.reply(LIST, list(row(G3, "GSTR3B")));
    open(G3);
    await screen.findByRole("heading", { name: "Enter GSTR-3B on the GST portal" });
    const text = (document.body.textContent ?? "").toLowerCase();
    expect(text).not.toMatch(/filed|ready to file/);
    expect(text).not.toMatch(/net payable|₹/);
  });

  it("is a not-found page for a GSTR-1 and an unknown id", async () => {
    server.reply(LIST, list(row(G1, "GSTR1")));
    open(G1);
    expect(await screen.findByRole("heading", { name: "We couldn't find that page" })).toBeTruthy();
  });

  it("is a not-found page for a billing member", async () => {
    server.reply(LIST, list(row(G3, "GSTR3B")));
    open(G3, "billing");
    expect(await screen.findByRole("heading", { name: "We couldn't find that page" })).toBeTruthy();
  });
});
