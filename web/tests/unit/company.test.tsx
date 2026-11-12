import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { changedKeys, patchBody, rebase, valuesOf } from "../../src/screens/settings/CompanyPage";
import { fyIst, previousFy } from "../../src/format/dates";
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

  describe("turnover bands", () => {
    const THIS = fyIst();
    const LAST = previousFy(THIS);
    const BAND = (fy: string) => `/api/v1/b/b-1/turnover-bands/${fy}`;
    const band = (fy: string, b: string, version: number) => ({ fy, band: b, declared_turnover: "4000000.00", version });
    const withBands = (over: Record<string, unknown> = {}) => profile({ turnover_band: band(THIS, "up_to_threshold", 2), previous_turnover_band: null, ...over });
    const group = (name: RegExp) => within(screen.getByRole("group", { name }));
    const puts = (fy: string) => server.sent.filter((s) => s.path === BAND(fy) && s.method === "PUT");

    it("saves each changed band on its own route: a first band with no If-Match, a change with its version", async () => {
      server.reply(PROFILE, { status: 200, body: withBands() });
      server.reply(BAND(THIS), { status: 200, body: band(THIS, "above_threshold", 3) });
      server.reply(BAND(LAST), { status: 200, body: { ...band(LAST, "up_to_threshold", 1), declared_turnover: null } });
      open();
      expect(await screen.findByText(`Not set yet. This decides whether 4-digit HSN codes are enough on your invoices.`)).toBeInTheDocument();
      fireEvent.click(group(/^Turnover this financial year/).getByRole("radio", { name: "Above that limit" }));
      fireEvent.click(group(/^Turnover last financial year/).getByRole("radio", { name: "Up to the limit for quarterly filing (QRMP)" }));
      fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
      expect(await screen.findByText(/Saved\./)).toBeInTheDocument();
      expect(patches()).toHaveLength(0); // nothing else changed
      expect(puts(THIS)[0].headers.get("If-Match")).toBe("2");
      expect(puts(THIS)[0].body).toEqual({ band: "above_threshold", declared_turnover: "4000000.00" }); // the declared amount is kept
      expect(puts(LAST)[0].headers.get("If-Match")).toBeNull();
      expect(puts(LAST)[0].body).toEqual({ band: "up_to_threshold", declared_turnover: null });
      expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled(); // the form is now what's saved
    });

    it("treats a band someone else set meanwhile (if_match_required) like a stale save", async () => {
      server.reply(PROFILE, { status: 200, body: withBands() }, { status: 200, body: withBands({ previous_turnover_band: band(LAST, "above_threshold", 1) }) });
      server.reply(BAND(LAST), { status: 422, body: { error: { code: "if_match_required", message: "Send the version you edited as If-Match", field: "If-Match" } } });
      open();
      await screen.findByLabelText("Legal name");
      fireEvent.click(group(/^Turnover last financial year/).getByRole("radio", { name: "Up to the limit for quarterly filing (QRMP)" }));
      fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
      expect(await screen.findByText(/Someone changed these details since you opened them/)).toBeInTheDocument();
      expect(screen.getByText("Now saved as: Above that limit")).toBeInTheDocument();
      expect(group(/^Turnover last financial year/).getByRole("radio", { name: "Up to the limit for quarterly filing (QRMP)" })).toBeChecked();
      expect(screen.queryByText("Send the version you edited as If-Match")).toBeNull();
    });

    it("after a save that half landed, keeps the unsaved edit without claiming someone else changed things", async () => {
      server.reply(PROFILE, { status: 200, body: withBands() });
      open();
      await screen.findByLabelText("Legal name");
      server.reply(PROFILE, { status: 200, body: { profile: withBands({ trade_name: "Vashi", version: 5 }), warnings: [] } });
      server.reply(BAND(THIS), { status: 500 }, { status: 200, body: band(THIS, "above_threshold", 3) });
      type("Trade name (optional)", "Vashi");
      fireEvent.click(group(/^Turnover this financial year/).getByRole("radio", { name: "Above that limit" }));
      fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
      expect(await screen.findByText(/Something went wrong on our side/)).toBeInTheDocument();
      expect(screen.getByLabelText("Trade name (optional)")).toHaveValue("Vashi");
      expect(group(/^Turnover this financial year/).getByRole("radio", { name: "Above that limit" })).toBeChecked();
      expect(screen.queryByText(/Someone changed these details/)).toBeNull();
      // The retry sends only what didn't land, against the version our PATCH left.
      fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
      expect(await screen.findByText(/Saved\./)).toBeInTheDocument();
      expect(patches()).toHaveLength(1);
      expect(puts(THIS)).toHaveLength(2);
    });

    it("after our PATCH lands and a band was set by someone else, blames only the band on them", async () => {
      server.reply(PROFILE, { status: 200, body: withBands() });
      open();
      await screen.findByLabelText("Legal name");
      server.reply(
        PROFILE,
        { status: 200, body: { profile: withBands({ trade_name: "Vashi", version: 5 }), warnings: [] } },
        { status: 200, body: withBands({ trade_name: "Vashi", version: 5, previous_turnover_band: band(LAST, "above_threshold", 1) }) },
      );
      server.reply(BAND(LAST), { status: 409, body: { error: { code: "stale_record", message: "This band changed since you opened it.", field: "If-Match" } } });
      type("Trade name (optional)", "Vashi");
      fireEvent.click(group(/^Turnover last financial year/).getByRole("radio", { name: "Up to the limit for quarterly filing (QRMP)" }));
      fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
      expect(await screen.findByText(/Someone changed these details since you opened them/)).toBeInTheDocument();
      expect(screen.getByText("Now saved as: Above that limit")).toBeInTheDocument();
      expect(screen.getAllByText(/Someone else changed this|Now saved as/)).toHaveLength(1); // the band only, not the trade name
      expect(screen.getByLabelText("Trade name (optional)")).toHaveValue("Vashi");
    });
  });

  it("shows the business-type field disabled with an Upcoming tag, and a save never sends it", async () => {
    server.reply(PROFILE, { status: 200, body: profile() }, { status: 200, body: { profile: profile({ trade_name: "Vashi", version: 5 }), warnings: [] } });
    open();
    await screen.findByLabelText("Legal name");
    expect(screen.getByLabelText(/Business type/)).toBeDisabled();
    expect(screen.getByText("Upcoming")).toBeInTheDocument();
    type("Trade name (optional)", "Vashi");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText(/Saved\./)).toBeInTheDocument();
    expect(JSON.stringify(patches()[0].body)).not.toMatch(/business_type/);
  });

  it("clears the last save's message on the next edit", async () => {
    server.reply(PROFILE, { status: 200, body: profile() }, { status: 200, body: { profile: profile({ trade_name: "Vashi", version: 5 }), warnings: [] } });
    open();
    await screen.findByLabelText("Legal name");
    type("Trade name (optional)", "Vashi");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText(/Saved\./)).toBeInTheDocument();
    type("Legal name", "Vashi Essentials Pvt Ltd");
    expect(screen.queryByText(/Saved\./)).toBeNull();
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
