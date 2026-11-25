import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { fyIst, previousFy, quarterStartIst, todayIst } from "../../src/format/dates";
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
const pickIn = (group: string | RegExp, name: string) =>
  fireEvent.click(within(screen.getByRole("group", { name: group })).getByRole("radio", { name }));
const THIS_YEAR = "Turnover this financial year (declared)";

function fillGstinBusiness() {
  type("GSTIN", GSTIN);
  type("Legal name (as on GST certificate)", "Vashi Essentials Pvt Ltd");
  type("Address line 1", "12 Market Road");
  type("City or town", "Pune");
  type("PIN code", "411001");
}

const CHANNELS = "/api/v1/b/b-1/channels";
const channelsSaved = { status: 200, body: { amazon: true, flipkart: false, meesho: false, own_invoices: false, answered: true } };
/** Step 4's turnover and e-invoicing answers (asked with how you sell and file, mocks v16). */
function answerTurnover() {
  pickIn(THIS_YEAR, "Up to the limit for quarterly filing (QRMP)");
  pick("No");
}
/** Step 3's Continue, then step 4: turnover, one platform, quarterly, Finish. `onStep4` runs after the turnover answers.
 *  A test that wants the channels call to fail queues its reply first. */
function submitAll(frequency: string | null = "Quarterly (QRMP)", onStep4?: () => void) {
  server.reply(CHANNELS, channelsSaved);
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  answerTurnover();
  onStep4?.();
  pickPlatform("Amazon");
  if (frequency) pick(frequency);
  finish();
}
const finish = () => fireEvent.click(screen.getByRole("button", { name: "Finish and see my filing home" }));
const pickPlatform = (name: string) => fireEvent.click(screen.getByRole("checkbox", { name }));

const sentTo = (path: string) => server.sent.filter((s) => s.path === path);

describe("the business-type field (ON-7, on in R2-M1)", () => {
  it("is optional: left alone, nothing is sent for it", async () => {
    await open();
    expect(screen.getByRole("group", { name: /What best describes your business/ })).toBeInTheDocument();
    for (const label of ["Retailer", "Wholesaler", "Distributor", "Manufacturer", "Online seller", "Service provider", "Other"]) {
      expect(screen.getByLabelText(label)).not.toBeChecked();
    }
    expect(screen.queryByText("Upcoming")).not.toBeInTheDocument();
    server.reply(CREATE, created());
    server.reply(FREQUENCY, chosen([]));
    server.reply(ME, me);
    fillGstinBusiness();
    submitAll();
    expect(await screen.findByRole("heading", { name: HOME })).toBeInTheDocument();
    expect(sentTo(CREATE)[0].body).not.toHaveProperty("business_types");
  });

  it("is sent as chosen", async () => {
    await open();
    fireEvent.click(screen.getByLabelText("Distributor"));
    fireEvent.click(screen.getByLabelText("Online seller"));
    server.reply(CREATE, created());
    server.reply(FREQUENCY, chosen([]));
    server.reply(ME, me);
    fillGstinBusiness();
    submitAll();
    expect(await screen.findByRole("heading", { name: HOME })).toBeInTheDocument();
    expect(sentTo(CREATE)[0].body).toMatchObject({ business_types: ["distributor", "online_seller"] });
  });
});

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

describe("where you sell (step 2 of the form)", () => {
  it("sends the ticked platforms, own invoices included, to the channels route", async () => {
    await open();
    server.reply(CREATE, created());
    server.reply(FREQUENCY, chosen());
    server.reply(ME, me);
    fillGstinBusiness();
    server.reply(CHANNELS, channelsSaved);
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    answerTurnover();
    pickPlatform("Flipkart");
    pickPlatform("Own sales invoices");
    pick("Monthly");
    finish();
    await screen.findByRole("heading", { name: HOME });
    expect(sentTo(CHANNELS)[0].body).toEqual({ amazon: false, flipkart: true, meesho: false, own_invoices: true });
  });

  it("keeps what you typed when you go Back, and sends nothing before Finish", async () => {
    await open();
    fillGstinBusiness();
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    pickPlatform("Amazon");
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByLabelText("PIN code")).toHaveValue("411001");
    expect(server.sent.filter((s) => s.path === CREATE || s.path === CHANNELS)).toHaveLength(0);
  });

  it("finishes with a note when the platforms can't be saved", async () => {
    await open();
    server.reply(CREATE, created());
    server.reply(FREQUENCY, chosen());
    server.reply(ME, me);
    fillGstinBusiness();
    server.reply(CHANNELS, { status: 400, body: { error: { code: "invalid", message: "x" } } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    answerTurnover();
    pickPlatform("Amazon");
    pick("Quarterly (QRMP)");
    finish();
    await screen.findByRole("heading", { name: HOME });
    expect(screen.getByText(/couldn't save where you sell/)).toBeInTheDocument();
  });
});

describe("saving the business", () => {
  it("creates the business, then the frequency from this quarter, and shows the warnings on Home", async () => {
    await open();
    server.reply(CREATE, created(["gstin_not_z"]));
    server.reply(FREQUENCY, chosen());
    server.reply(ME, me);
    fillGstinBusiness();
    submitAll();
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

  it("saves last year's band, when given, for the year before this one, with no If-Match", async () => {
    const BAND = `/api/v1/b/b-1/turnover-bands/${previousFy(fyIst())}`;
    await open();
    server.reply(CREATE, created());
    server.reply(BAND, { status: 200, body: { fy: previousFy(fyIst()), band: "above_threshold", declared_turnover: null, version: 1 } });
    server.reply(FREQUENCY, chosen([]));
    server.reply(ME, me);
    fillGstinBusiness();
    submitAll(undefined, () => pickIn(`What was your turnover last financial year (FY ${previousFy(fyIst())})? (optional)`, "Above that limit"));
    expect(await screen.findByRole("heading", { name: HOME })).toBeInTheDocument();
    const [band] = sentTo(BAND);
    expect(band.method).toBe("PUT");
    expect(band.body).toEqual({ band: "above_threshold", declared_turnover: null });
    expect(band.headers.get("If-Match")).toBeNull();
  });

  it("sends no band for Not sure, and finishes sign-up with a note when last year's band fails", async () => {
    const BAND = `/api/v1/b/b-1/turnover-bands/${previousFy(fyIst())}`;
    await open();
    server.reply(CREATE, created());
    server.reply(BAND, { status: 500 });
    server.reply(FREQUENCY, chosen([]));
    server.reply(ME, me);
    fillGstinBusiness();
    const lastYear = `What was your turnover last financial year (FY ${previousFy(fyIst())})? (optional)`;
    submitAll(undefined, () => {
      pickIn(lastYear, "Not sure");
      pickIn(lastYear, "Up to the limit for quarterly filing (QRMP)");
    });
    expect(await screen.findByRole("heading", { name: HOME })).toBeInTheDocument();
    expect(screen.getByText(/We couldn't save last year's turnover\. Add it in Settings → Business details\./)).toBeInTheDocument();
  });

  it("treats last year's band as saved when a replayed create finds it already there", async () => {
    const BAND = `/api/v1/b/b-1/turnover-bands/${previousFy(fyIst())}`;
    await open();
    server.reply(CREATE, created());
    // What business/profile.py sends for a PUT with no If-Match when the band already exists.
    server.reply(BAND, { status: 422, body: { error: { code: "if_match_required", message: "Send the version you edited as If-Match", field: "If-Match" } } });
    server.reply(FREQUENCY, chosen([]));
    server.reply(ME, me);
    fillGstinBusiness();
    submitAll(undefined, () => pickIn(/^What was your turnover last financial year/, "Above that limit"));
    expect(await screen.findByRole("heading", { name: HOME })).toBeInTheDocument();
    expect(screen.queryByText(/We couldn't save last year's turnover/)).toBeNull();
  });

  it("sends nothing for last year when the answer is Not sure", async () => {
    await open();
    server.reply(CREATE, created());
    server.reply(FREQUENCY, chosen([]));
    server.reply(ME, me);
    fillGstinBusiness();
    submitAll(undefined, () => pickIn(/^What was your turnover last financial year/, "Not sure"));
    expect(await screen.findByRole("heading", { name: HOME })).toBeInTheDocument();
    expect(server.paths().some((p) => p.includes("/turnover-bands/"))).toBe(false);
  });

  it("reuses the same Idempotency-Key when the first try didn't get through", async () => {
    await open();
    server.reply(CREATE, { status: 503 }, created());
    server.reply(FREQUENCY, chosen());
    server.reply(ME, me);
    fillGstinBusiness();
    submitAll();
    expect(await screen.findByText(/Something went wrong on our side/)).toBeInTheDocument();
    finish();
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
    submitAll();
    const pin = await screen.findByLabelText("PIN code");
    await waitFor(() => expect(pin).toHaveAttribute("aria-invalid", "true"));
    expect(screen.getByText("Enter a 6-digit PIN code.")).toBeInTheDocument();
    expect(pin).toHaveFocus();
  });

  it("checks the required answers before sending anything", async () => {
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.getByText("Enter your GSTIN.")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "Amazon" })).toBeNull(); // still on step 3
    fillGstinBusiness();
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    finish();
    expect(screen.getAllByText("Choose one.")).toHaveLength(2); // turnover and e-invoicing, now on step 4
    expect(screen.getByText("Pick at least one to continue.")).toBeInTheDocument();
    expect(screen.getByText("Choose how often you file GST.")).toBeInTheDocument();
    expect(sentTo(CREATE)).toHaveLength(0);
    expect(sentTo(CHANNELS)).toHaveLength(0);
  });

  it("sends an enrolment number with its state, and no frequency", async () => {
    await open();
    server.reply(CREATE, created());
    server.reply(ME, me);
    fireEvent.click(screen.getByRole("button", { name: "Use enrolment number" }));
    type("Enrolment number", " EN123 ");
    type("State you're enrolled in", "19");
    submitAll(null, () => pickIn(/e-invoicing limit/, "Not sure"));
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
    submitAll();
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
    submitAll();
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

describe("GSTIN lookup (#249): fills the form, never blocks it", () => {
  const LOOKUP = "/api/v1/gstin-lookup";
  const found = (over: Record<string, unknown> = {}) => ({
    status: 200,
    body: {
      found: true, gstin: GSTIN, legal_name: "Demo Traders Pvt Ltd", trade_name: "Demo Traders", status: "Active", source: "demo",
      address: { line1: "12 Sample Road", line2: "Demo Market", city: "Mumbai", pin: "400001", state_code: "27" }, ...over,
    },
  });

  it("fills empty fields from a well-formed GSTIN and says where they came from", async () => {
    server.reply(LOOKUP, found());
    await open();
    type("GSTIN", GSTIN);
    await waitFor(() => expect(screen.getByLabelText("Legal name (as on GST certificate)")).toHaveValue("Demo Traders Pvt Ltd"));
    expect(screen.getByLabelText("Trade name (optional)")).toHaveValue("Demo Traders");
    expect(screen.getByLabelText("City or town")).toHaveValue("Mumbai");
    expect(screen.getByLabelText("PIN code")).toHaveValue("400001");
    expect(screen.getByText(/made-up demo details/)).toBeInTheDocument();
    expect(screen.queryByText(/verified/i)).toBeNull();
    expect(sentTo(LOOKUP)).toHaveLength(1);
    expect(sentTo(LOOKUP)[0].body).toEqual({ gstin: GSTIN });
  });

  it("keeps what the person already typed, and lets them type over what it filled", async () => {
    server.reply(LOOKUP, found());
    await open();
    type("Legal name (as on GST certificate)", "My own name");
    type("GSTIN", GSTIN);
    await waitFor(() => expect(screen.getByLabelText("City or town")).toHaveValue("Mumbai"));
    expect(screen.getByLabelText("Legal name (as on GST certificate)")).toHaveValue("My own name");
    type("City or town", "Pune");
    expect(screen.getByLabelText("City or town")).toHaveValue("Pune");
  });

  it("does not ask for a GSTIN that is not well formed", async () => {
    await open();
    type("GSTIN", "27AAPFU0939F1ZX");
    type("GSTIN", "27AAPFU");
    expect(sentTo(LOOKUP)).toHaveLength(0);
  });

  it("warns when the lookup shows a registration that is not active, without stopping", async () => {
    server.reply(LOOKUP, found({ status: "Cancelled" }));
    await open();
    type("GSTIN", GSTIN);
    expect(await screen.findByText(/shows this registration as "Cancelled"/)).toBeInTheDocument();
  });

  it("says plainly when nothing was found, and leaves the form alone", async () => {
    server.reply(LOOKUP, { status: 200, body: { found: false, gstin: GSTIN, legal_name: null, trade_name: null, status: null, address: null, source: "demo" } });
    await open();
    type("GSTIN", GSTIN);
    expect(await screen.findByText(/found no details for this GSTIN/)).toBeInTheDocument();
    expect(screen.getByLabelText("Legal name (as on GST certificate)")).toHaveValue("");
  });

  it("carries on by hand when the lookup fails, is limited, or is off", async () => {
    server.reply(LOOKUP, { status: 503, body: { error: { code: "lookup_unavailable", message: "x" } } });
    await open();
    type("GSTIN", GSTIN);
    expect(await screen.findByText(/couldn't fetch your details right now/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    type("GSTIN", "19AAPFU0939F1ZS");
    server.reply(LOOKUP, { status: 429, body: { error: { code: "rate_limited", message: "x" } }, headers: { "Retry-After": "60" } });
    type("GSTIN", "");
    type("GSTIN", "19AAPFU0939F1ZS");
    expect(await screen.findByText(/paused the lookup/)).toBeInTheDocument();
  });

  it("says nothing when the lookup is switched off, and the form still submits", async () => {
    server.reply(LOOKUP, { status: 503, body: { error: { code: "lookup_off", message: "x" } } });
    await open();
    fillGstinBusiness();
    await waitFor(() => expect(sentTo(LOOKUP)).toHaveLength(1));
    expect(screen.queryByText(/couldn't fetch/)).toBeNull();
    server.reply(CREATE, created());
    server.reply(FREQUENCY, chosen());
    server.reply(ME, me);
    submitAll();
    await screen.findByRole("heading", { name: HOME });
    expect(sentTo(CREATE)[0].body).toMatchObject({ legal_name: "Vashi Essentials Pvt Ltd" });
  });
});
