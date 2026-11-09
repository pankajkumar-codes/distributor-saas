import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { grouped, otpauthUri } from "../../src/screens/settings/SecurityPage";
import { fakeApi } from "./fakeApi";

// Two-step sign-in (TD-4a): enrolment in Settings (LLD-1 §5.9), the Home prompt for owners
// and CAs, and support's removal after an email-code check (LLD-2 §6.3).
const REFRESH = "/api/v1/auth/refresh";
const BUSINESSES = "/api/v1/me/businesses";
const ME = "/api/v1/me";
const SETUP = "/api/v1/me/totp/setup";
const CONFIRM = "/api/v1/me/totp/confirm";
const TOTP = "/api/v1/me/totp";
const SIGNOUT = "/api/v1/auth/signout";
const HOME = "/api/v1/b/b-1/home";
const GRANTS = "/api/v1/support/grants";
const RECOVER = "/api/v1/support/totp-recovery";
const RECOVER_CONFIRM = "/api/v1/support/totp-recovery/confirm";
const SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP";
const mine = (role = "owner") => ({
  status: 200,
  body: { businesses: [{ business_id: "b-1", display_name: "Vashi Essentials", gstin: null, role }], is_support: false },
});
const me = (totp_enabled: boolean, is_support = false) => ({
  status: 200,
  body: { user: { id: "u-1", email: "owner@vashi.example", name: "Pankaj", totp_enabled, is_support }, memberships: [] },
});
const refused = (status: number, code: string) => ({ status, body: { error: { code, message: code } } });
const home = {
  status: 200,
  body: { greeting_name: null, checklist: { done: 0, total: 0, items: [] }, filing: null, hub: null, insights: null, attention: [] },
};

let server: ReturnType<typeof fakeApi>;
beforeEach(() => {
  resetSessionForTests();
  server = fakeApi();
  server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
});
afterEach(() => vi.unstubAllGlobals());

function open(path: string) {
  window.history.replaceState(null, "", path);
  render(<App />);
}
const enter = (code: string) => fireEvent.paste(screen.getByLabelText("Digit 1 of 6"), { clipboardData: { getData: () => code } });
const posts = (path: string) => server.sent.filter((s) => s.path === path && s.method === "POST");

describe("the key for the authenticator app", () => {
  it("names the app and the account, and is drawn from the server's secret only", () => {
    expect(otpauthUri(SECRET, "a+b@x.in", "Business Hub")).toBe(
      `otpauth://totp/Business%20Hub:a%2Bb%40x.in?secret=${SECRET}&issuer=Business%20Hub`,
    );
    expect(grouped("ABCDEFGHIJ")).toBe("ABCD EFGH IJ");
  });
});

describe("Settings › Two-step sign-in", () => {
  it("turns it on: a QR code and the key, then one code from the app", async () => {
    server.reply(BUSINESSES, mine());
    server.reply(ME, me(false), me(true));
    server.reply(SETUP, { status: 200, body: { secret: SECRET } });
    server.reply(CONFIRM, refused(422, "totp_not_accepted"), { status: 204 });
    open("/b/b-1/settings/security");
    expect(await screen.findByText(/We recommend turning this on/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Turn on two-step sign-in" }));
    expect(await screen.findByRole("img", { name: "QR code for your authenticator app" })).toHaveAttribute(
      "src",
      expect.stringMatching(/^data:image\/svg\+xml/),
    );
    expect(screen.getByText(grouped(SECRET))).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Turn on" }));
    expect(await screen.findByText("Enter all 6 digits.")).toBeInTheDocument();
    expect(posts(CONFIRM)).toHaveLength(0);
    enter("111111");
    fireEvent.click(screen.getByRole("button", { name: "Turn on" }));
    expect(await screen.findByText(/That code didn't work/)).toBeInTheDocument();
    enter("222222");
    fireEvent.click(screen.getByRole("button", { name: "Turn on" }));
    expect(await screen.findByText(/Two-step sign-in is on\./)).toBeInTheDocument();
    expect(posts(CONFIRM).map((s) => s.body)).toEqual([{ code: "111111" }, { code: "222222" }]);
    expect(await screen.findByRole("button", { name: "Turn off two-step sign-in" })).toBeInTheDocument();
    expect(screen.queryByText(grouped(SECRET))).toBeNull(); // the secret isn't kept once it's on
  });

  it("asks before turning it off, then turns it off", async () => {
    server.reply(BUSINESSES, mine("billing"));
    server.reply(ME, me(true), me(false));
    server.reply(TOTP, { status: 204 });
    open("/b/b-1/settings/security");
    fireEvent.click(await screen.findByRole("button", { name: "Turn off two-step sign-in" }));
    fireEvent.click(screen.getByRole("button", { name: "Keep it on" }));
    expect(server.sent.some((s) => s.path === TOTP)).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Turn off two-step sign-in" }));
    fireEvent.click(screen.getByRole("button", { name: "Yes, turn it off" }));
    expect(await screen.findByText("Two-step sign-in is off.")).toBeInTheDocument();
    expect(server.sent.filter((s) => s.path === TOTP).map((s) => s.method)).toEqual(["DELETE"]);
    expect(await screen.findByRole("button", { name: "Turn on two-step sign-in" })).toBeInTheDocument();
    expect(screen.queryByText(/We recommend/)).toBeNull(); // billing isn't asked to
  });

  it("sends the user to sign in again, and back here, when the sign-in is too old to turn it off", async () => {
    server.reply(BUSINESSES, mine());
    server.reply(ME, me(true));
    server.reply(TOTP, refused(409, "reauth_required"));
    server.reply(SIGNOUT, { status: 204 });
    open("/b/b-1/settings/security");
    fireEvent.click(await screen.findByRole("button", { name: "Turn off two-step sign-in" }));
    fireEvent.click(screen.getByRole("button", { name: "Yes, turn it off" }));
    fireEvent.click(await screen.findByRole("button", { name: "Sign in again" }));
    await waitFor(() => expect(window.location.pathname).toBe("/signin"));
    expect(new URLSearchParams(window.location.search).get("next")).toBe("/b/b-1/settings/security");
    expect(posts(SIGNOUT)).toHaveLength(1);
  });

  it("is not found for a business that isn't yours", async () => {
    server.reply(BUSINESSES, mine());
    server.reply(ME, me(false));
    open("/b/b-9/settings/security");
    expect(await screen.findByRole("heading", { name: "We couldn't find that page" })).toBeInTheDocument();
  });
});

describe("the prompt on Home", () => {
  it.each(["owner", "ca"])("asks the %s to turn it on while it's off", async (role) => {
    server.reply(BUSINESSES, mine(role));
    server.reply(HOME, home);
    server.reply(ME, me(false));
    open("/b/b-1/home");
    expect(await screen.findByRole("link", { name: "Turn on two-step sign-in" })).toHaveAttribute("href", "/b/b-1/settings/security");
    expect(screen.getByRole("link", { name: "Two-step sign-in" })).toBeInTheDocument();
  });

  it("doesn't ask once it's on, and never asks other roles", async () => {
    server.reply(BUSINESSES, mine("billing"));
    server.reply(HOME, home);
    open("/b/b-1/home");
    expect(await screen.findByRole("link", { name: "Two-step sign-in" })).toBeInTheDocument();
    expect(server.paths()).not.toContain(ME);
    expect(screen.queryByText("Protect your account")).toBeNull();
  });
});

describe("support removes someone's two-step sign-in", () => {
  it("emails the account a code, then takes the code the person reads out", async () => {
    server.reply(RECOVER, { status: 202, body: { code_ttl_minutes: 10, code_max_tries: 5 } });
    server.reply(RECOVER_CONFIRM, refused(400, "code_not_accepted"), { status: 204 });
    open("/support/totp-recovery");
    fireEvent.click(await screen.findByRole("button", { name: "Email them a code" }));
    expect(screen.getByText("Enter the account's email.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Their account email"), { target: { value: " lost@phone.example " } });
    fireEvent.click(screen.getByRole("button", { name: "Email them a code" }));
    // The same words whether or not the account exists (the server's reply is uniform too).
    expect(await screen.findByText(/If lost@phone\.example has two-step sign-in on/)).toHaveTextContent("10 minutes and 5 tries");
    enter("123456");
    fireEvent.click(screen.getByRole("button", { name: "Remove two-step sign-in" }));
    expect(await screen.findByText(/That code didn't work/)).toBeInTheDocument();
    enter("654321");
    fireEvent.click(screen.getByRole("button", { name: "Remove two-step sign-in" }));
    expect(await screen.findByText(/Two-step sign-in is off for lost@phone\.example/)).toBeInTheDocument();
    expect(posts(RECOVER).map((s) => s.body)).toEqual([{ email: "lost@phone.example" }]);
    expect(posts(RECOVER_CONFIRM).map((s) => s.body)).toEqual([
      { email: "lost@phone.example", code: "123456" },
      { email: "lost@phone.example", code: "654321" },
    ]);
  });

  it("is not found for anyone the server refuses", async () => {
    server.reply(RECOVER, refused(404, "not_found"));
    open("/support/totp-recovery");
    fireEvent.change(await screen.findByLabelText("Their account email"), { target: { value: "x@y.in" } });
    fireEvent.click(screen.getByRole("button", { name: "Email them a code" }));
    expect(await screen.findByRole("heading", { name: "We couldn't find that page" })).toBeInTheDocument();
  });

  it("sends support staff without two-step sign-in to turn it on", async () => {
    server.reply(GRANTS, refused(404, "not_found"));
    server.reply(ME, me(false, true));
    open("/support");
    expect(await screen.findByRole("heading", { name: "Turn on two-step sign-in first" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Turn on two-step sign-in" })).toHaveAttribute("href", "/account/security");
  });

  it("lets support staff turn theirs on at /account/security", async () => {
    server.reply(BUSINESSES, { status: 200, body: { businesses: [], is_support: true } });
    server.reply(GRANTS, refused(404, "not_found"));
    server.reply(ME, me(false, true));
    open("/account/security");
    expect(await screen.findByText(/Support staff must turn this on/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Turn on two-step sign-in" })).toBeInTheDocument();
  });
});
