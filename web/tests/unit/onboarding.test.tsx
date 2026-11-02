import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { quarterStartIst, todayIst } from "../../src/format/dates";
import { checkCharacter } from "../../src/format/gstin";
import { resetSessionForTests } from "../../src/auth/session";
import { fieldError } from "../../src/screens/onboarding/BusinessPage";
import { fakeApi } from "./fakeApi";

const HOME = /^(Welcome|Good (morning|afternoon|evening))/; // Home's h1 is the greeting
const REFRESH = "/api/v1/auth/refresh";
const STATES = "/api/v1/refdata/state-codes";
const CREATE = "/api/v1/b";
const FREQUENCY = "/api/v1/b/b-1/filing-profile/frequency";
const ME = "/api/v1/me/businesses";
const GSTIN = "27AAPFU0939F1ZV";
const states = {
  status: 200,
  body: {
    on: "2026-10-27",
    states: [
      { code: "19", name: "West Bengal" },
      { code: "27", name: "Maharashtra" },
      { code: "96", name: "Other Country" },
    ],
  },
};
const created = (warnings: string[] = []) => ({ status: 201, body: { business_id: "b-1", warnings } });
const chosen = (warnings: string[] = ["window_unknown"]) => ({
  status: 201,
  body: { row: { id: "r1", gstin: GSTIN, frequency: "quarterly", effective_from: "2026-10-01", chosen_at: "", warnings }, warnings, superseded_instances: [] },
});
const me = { status: 200, body: { businesses: [{ business_id: "b-1", display_name: "Vashi Essentials", gstin: GSTIN, role: "owner" }] } };

let server: ReturnType<typeof fakeApi>;

beforeEach(() => {
  resetSessionForTests();
  server = fakeApi();
  server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
  server.reply(STATES, states);
});
afterEach(() => vi.unstubAllGlobals());

async function open() {
  window.history.replaceState(null, "", "/onboarding/business");
  render(<App />);
  await screen.findByRole("heading", { name: "Your business and GST" });
  await screen.findAllByRole("option", { name: "Maharashtra (27)" });
}

const type = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
const pick = (name: string) => fireEvent.click(screen.getByRole("radio", { name }));

function fillGstinBusiness() {
  type("GSTIN", GSTIN);
  type("Legal name (as on GST certificate)", "Vashi Essentials Pvt Ltd");
  pick("Up to the limit for quarterly filing (QRMP)");
  pick("No");
  type("Address line 1", "12 Market Road");
  type("City or town", "Pune");
  type("PIN code", "411001");
  pick("Every quarter (QRMP)");
}

const sentTo = (path: string) => server.sent.filter((s) => s.path === path);

describe("the GSTIN hint", () => {
  it("says the format looks right and names the state, and never says verified", async () => {
    await open();
    type("GSTIN", " 27aapfu0939f1zv ");
    expect(screen.getByText(/Format and check digit look right\. State code 27 \(Maharashtra\)\./)).toBeInTheDocument();
    expect(screen.getByText(/not with the GST portal/)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/verified/i);
  });

  it("shows the server's words for a wrong check character", async () => {
    await open();
    type("GSTIN", "27AAPFU0939F1ZA");
    expect(screen.getByText("GSTIN check character doesn't match; please re-check the number.")).toBeInTheDocument();
  });

  it("waits for 15 characters or leaving the field before saying it's short", async () => {
    await open();
    type("GSTIN", "27AAPFU");
    expect(screen.queryByText(/it needs 15/)).toBeNull();
    fireEvent.blur(screen.getByLabelText("GSTIN"));
    expect(screen.getByText("GSTIN has 7 characters; it needs 15.")).toBeInTheDocument();
  });

  it("refuses a first two digits that aren't a state", async () => {
    await open();
    type("GSTIN", "99AAPFU0939F1Z" + checkCharacter("99AAPFU0939F1Z"));
    expect(screen.getByText("The first two digits of a GSTIN must be a state code.")).toBeInTheDocument();
    expect(screen.queryByText(/State code 99/)).toBeNull();
  });

  it("leaves 96 out of the state pickers", async () => {
    await open();
    expect(screen.queryByRole("option", { name: /Other Country/ })).toBeNull();
  });
});

describe("saving the business", () => {
  it("creates the business, then the frequency from this quarter, and shows the warnings on Home", async () => {
    await open();
    server.reply(CREATE, created(["gstin_not_z"]));
    server.reply(FREQUENCY, chosen());
    server.reply(ME, me);
    fillGstinBusiness();
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByRole("heading", { name: HOME })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/b/b-1/home");

    const [business] = sentTo(CREATE);
    expect(business.body).toEqual({
      registration: { kind: "gstin", gstin: GSTIN },
      legal_name: "Vashi Essentials Pvt Ltd",
      trade_name: null,
      turnover_band: "up_to_threshold",
      einvoice_history: "no",
      address: { line1: "12 Market Road", line2: null, city: "Pune", pin: "411001", state_code: "27" },
    });
    expect(business.headers.get("Idempotency-Key")).toMatch(/^[0-9a-f-]{36}$/);
    const [frequency] = sentTo(FREQUENCY);
    expect(frequency.body).toEqual({ frequency: "quarterly", effective_from: quarterStartIst() });
    expect(frequency.headers.get("Idempotency-Key")).not.toBe(business.headers.get("Idempotency-Key"));
    expect(screen.getByText(/14th character of a GSTIN is usually Z/)).toBeInTheDocument();
    expect(screen.getByText(/can't show the dates for changing your filing frequency/)).toBeInTheDocument();
  });

  it("reuses the same Idempotency-Key when the first try didn't get through", async () => {
    await open();
    server.reply(CREATE, { status: 503 }, created());
    server.reply(FREQUENCY, chosen());
    server.reply(ME, me);
    fillGstinBusiness();
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByText(/Something went wrong on our side/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByRole("heading", { name: HOME });
    const [first, second] = sentTo(CREATE);
    expect(second.headers.get("Idempotency-Key")).toBe(first.headers.get("Idempotency-Key"));
  });

  it("puts the server's refusal under the field it names", async () => {
    await open();
    server.reply(CREATE, {
      status: 422,
      body: { error: { code: "invalid", message: "String should match pattern", field: "address.pin" } },
    });
    fillGstinBusiness();
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    const pin = screen.getByLabelText("PIN code");
    await waitFor(() => expect(pin).toHaveAttribute("aria-invalid", "true"));
    expect(screen.getByText("Enter a 6-digit PIN code.")).toBeInTheDocument();
    expect(pin).toHaveFocus();
  });

  it("checks the required answers before sending anything", async () => {
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.getByText("Enter your GSTIN.")).toBeInTheDocument();
    expect(screen.getAllByText("Choose one.")).toHaveLength(2);
    expect(screen.getByText("Choose how often you file GSTR-1.")).toBeInTheDocument();
    expect(sentTo(CREATE)).toHaveLength(0);
  });

  it("sends an enrolment number with its state, and no frequency", async () => {
    await open();
    server.reply(CREATE, created());
    server.reply(ME, me);
    fireEvent.click(screen.getByRole("button", { name: "Use enrolment number" }));
    type("Enrolment number", " EN123 ");
    type("State you're enrolled in", "19");
    pick("Up to the limit for quarterly filing (QRMP)");
    pick("Not sure");
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByRole("heading", { name: HOME });
    expect(sentTo(CREATE)[0].body).toMatchObject({
      registration: { kind: "enrolment", enrolment_number: "EN123", state_code: "19" },
      address: { state_code: "19" },
    });
    expect(sentTo(FREQUENCY)).toHaveLength(0);
  });

  it("warns as you choose an address in another state", async () => {
    await open();
    type("GSTIN", GSTIN);
    expect(screen.getByLabelText("State")).toHaveValue("27");
    type("State", "19");
    expect(screen.getByText(/different state from your GSTIN/)).toBeInTheDocument();
  });

  it("offers to retry or skip only the frequency when the business saved but it didn't", async () => {
    await open();
    server.reply(CREATE, created());
    server.reply(FREQUENCY, { status: 503 }, chosen([]));
    server.reply(ME, me);
    fillGstinBusiness();
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByText(/Your business is saved, but we couldn't save how often you file/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findByRole("heading", { name: HOME });
    expect(sentTo(CREATE)).toHaveLength(1);
    const [first, second] = sentTo(FREQUENCY);
    expect(second.headers.get("Idempotency-Key")).toBe(first.headers.get("Idempotency-Key"));
  });

  it("says the business may already exist when the key was used for a different form", async () => {
    await open();
    server.reply(CREATE, { status: 409, body: { error: { code: "idempotency_mismatch", message: "x" } } });
    fillGstinBusiness();
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByText(/may already have been saved/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Check your businesses" })).toHaveAttribute("href", "/businesses");
  });
});

describe("helpers", () => {
  it("maps server field paths and codes to the screen's words", () => {
    const e = (code: string, field?: string) => ({ status: 422, code, message: "", field });
    expect(fieldError(e("gstin_length", "registration.gstin"), "27AAPFU0939F1Z")).toEqual({
      field: "registration.gstin",
      text: "GSTIN has 14 characters; it needs 15.",
    });
    expect(fieldError(e("registration_required", "registration"), "")?.field).toBe("registration.gstin");
    expect(fieldError(e("state_code_unknown", "address.state_code"), "")?.text).toBe("Choose a state from the list.");
    expect(fieldError(e("invalid", "address.city"), "")?.text).toBe("Check this entry.");
    expect(fieldError(e("internal"), "")).toBeNull();
  });

  it("takes today and the quarter in India, not the browser's zone", () => {
    // 30 Sep 2026 20:00 UTC is already 1 Oct in India.
    const late = new Date(Date.UTC(2026, 8, 30, 20, 0));
    expect(todayIst(late)).toBe("2026-10-01");
    expect(quarterStartIst(late)).toBe("2026-10-01");
    expect(quarterStartIst(new Date(Date.UTC(2026, 2, 31, 12)))).toBe("2026-01-01");
    expect(quarterStartIst(new Date(Date.UTC(2026, 5, 15)))).toBe("2026-04-01");
  });
});
