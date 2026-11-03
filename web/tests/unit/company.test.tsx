import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { changedKeys, patchBody, rebase, valuesOf } from "../../src/screens/settings/CompanyPage";
import { fakeApi } from "./fakeApi";

const REFRESH = "/api/v1/auth/refresh";
const ME = "/api/v1/me/businesses";
const STATES = "/api/v1/refdata/state-codes";
const PROFILE = "/api/v1/b/b-1/profile";
const me = (role = "owner") => ({
  status: 200,
  body: { businesses: [{ business_id: "b-1", display_name: "Vashi Essentials", gstin: "19ABCDE1234F1Z5", role }] },
});
const states = { status: 200, body: { on: "2026-11-03", states: [{ code: "19", name: "West Bengal" }, { code: "27", name: "Maharashtra" }] } };
const profile = (over: Record<string, unknown> = {}) => ({
  business_id: "b-1",
  legal_name: "Vashi Essentials Private Limited",
  trade_name: "Vashi Essentials",
  registration: { kind: "gstin", gstin: "19ABCDE1234F1Z5", enrolment_number: null, state_code: "19", state_name: "West Bengal", locked: false },
  address: { line1: "12 Lake Road", line2: null, city: "Kolkata", pin: "700029", state_code: "19" },
  einvoice_history: "no",
  turnover_band: null,
  ready_for_documents: { ok: true, missing: [] },
  version: 4,
  ...over,
});

let server: ReturnType<typeof fakeApi>;
beforeEach(() => {
  resetSessionForTests();
  server = fakeApi();
  server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
  server.reply(STATES, states);
});
afterEach(() => vi.unstubAllGlobals());

function open(role = "owner") {
  server.reply(ME, me(role), me(role));
  window.history.replaceState(null, "", "/b/b-1/settings/company");
  render(<App />);
}
const type = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
const patches = () => server.sent.filter((s) => s.path === PROFILE && s.method === "PATCH");

describe("business details", () => {
  it("sends only the changed fields with If-Match, and shows the server's warnings", async () => {
    server.reply(PROFILE, { status: 200, body: profile() });
    open();
    expect(await screen.findByLabelText("Legal name")).toHaveValue("Vashi Essentials Private Limited");
    expect(screen.getByText("GSTIN 19ABCDE1234F1Z5, West Bengal")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled(); // nothing changed yet

    server.reply(PROFILE, {
      status: 200,
      body: { profile: profile({ trade_name: "Vashi", address: { ...profile().address, state_code: "27" }, version: 5 }), warnings: ["address_state_mismatch"] },
    });
    type("Trade name (optional)", "Vashi");
    fireEvent.change(screen.getByLabelText("State"), { target: { value: "27" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText(/Saved\. Invoices already finalized keep/)).toBeInTheDocument();
    expect(screen.getByText(/Your address is in a different state from your GSTIN/)).toBeInTheDocument();
    const [patch] = patches();
    expect(patch.body).toEqual({ trade_name: "Vashi", address: { line1: "12 Lake Road", line2: null, city: "Kolkata", pin: "700029", state_code: "27" } });
    expect(patch.headers.get("If-Match")).toBe("4");
  });

  it("after someone else saved first, keeps both people's changes and saves against the newer version", async () => {
    server.reply(PROFILE, { status: 200, body: profile() });
    open();
    await screen.findByLabelText("Legal name");
    server.reply(
      PROFILE,
      { status: 409, body: { error: { code: "stale_record", message: "Someone changed these details since you opened them" } } },
      { status: 200, body: profile({ einvoice_history: "yes", version: 5 }) },
      { status: 200, body: { profile: profile({ einvoice_history: "yes", trade_name: "Vashi", version: 6 }), warnings: [] } },
    );
    type("Trade name (optional)", "Vashi");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText(/Someone changed these details since you opened them\. Your changes are still here/)).toBeInTheDocument();
    expect(screen.getByText("Someone else changed this.")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Yes" })).toBeChecked();
    expect(screen.getByLabelText("Trade name (optional)")).toHaveValue("Vashi");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await screen.findByText(/Saved\./);
    const [first, second] = patches();
    expect(first.headers.get("If-Match")).toBe("4");
    expect(second.headers.get("If-Match")).toBe("5");
    expect(second.body).toEqual({ trade_name: "Vashi" });
  });

  it("puts the server's field error on its field", async () => {
    server.reply(PROFILE, { status: 200, body: profile() });
    open();
    await screen.findByLabelText("Legal name");
    server.reply(PROFILE, { status: 422, body: { error: { code: "invalid", message: "Use 6 digits", field: "address.pin" } } });
    type("PIN code", "7000");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("Use 6 digits")).toBeInTheDocument();
    expect(screen.getByLabelText("PIN code")).toHaveAttribute("aria-invalid", "true");
  });

  it("says what is still needed before the first invoice", async () => {
    server.reply(PROFILE, { status: 200, body: profile({ legal_name: null, ready_for_documents: { ok: false, missing: ["legal_name", "address"] } }) });
    open();
    expect(await screen.findByText("Needed before your first invoice: legal name, address.")).toBeInTheDocument();
  });

  it("says a missing GSTIN can't be added in the app yet, rather than promising a field", async () => {
    server.reply(PROFILE, {
      status: 200,
      body: profile({
        registration: { kind: "enrolment", gstin: null, enrolment_number: "EN1234567890", state_code: "19", state_name: "West Bengal", locked: false },
        ready_for_documents: { ok: false, missing: ["gstin"] },
      }),
    });
    open();
    expect(await screen.findByText(/Needed before your first invoice: GSTIN\. Adding a GSTIN isn't available in the app yet\./)).toBeInTheDocument();
    expect(screen.getByText("Enrolment number EN1234567890, West Bengal")).toBeInTheDocument();
  });

  it("shows a load failure with Try again, not an empty form", async () => {
    server.reply(PROFILE, { status: 500 }, { status: 500 }, { status: 500 }, { status: 200, body: profile() });
    open();
    expect(await screen.findByText(/We couldn't load your business details/, {}, { timeout: 8000 })).toBeInTheDocument();
    expect(screen.queryByLabelText("Legal name")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByLabelText("Legal name")).toBeInTheDocument();
  }, 12000);

  it("shows the details read-only to a role that can't change settings", async () => {
    server.reply(PROFILE, { status: 200, body: profile() });
    open("billing");
    expect(await screen.findByLabelText("Legal name")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Save changes" })).toBeNull();
  });

  it("is NotFound for another business", async () => {
    server.reply(ME, { status: 200, body: { businesses: [] } });
    window.history.replaceState(null, "", "/b/b-1/settings/company");
    render(<App />);
    expect(await screen.findByText(/couldn't find that page/i)).toBeInTheDocument();
    expect(server.paths()).not.toContain(PROFILE);
  });
});

describe("the business details edit rules", () => {
  const opened = valuesOf(profile() as never);
  it("sends a cleared trade name as null and an address whole", () => {
    const to = { ...opened, trade_name: " ", address: { ...opened.address, city: "Howrah" } };
    expect(changedKeys(opened, to)).toEqual(["trade_name", "address"]);
    expect(patchBody(opened, to)).toEqual({ trade_name: null, address: { line1: "12 Lake Road", line2: null, city: "Howrah", pin: "700029", state_code: "19" } });
  });
  it("lays the user's edits over the newer saved values", () => {
    const latest = { ...opened, legal_name: "Vashi Essentials LLP" };
    const mine = { ...opened, einvoice_history: "yes" as const };
    expect(rebase(opened, latest, mine)).toEqual({ ...latest, einvoice_history: "yes" });
  });
});
