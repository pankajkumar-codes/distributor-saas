import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { tokenStore } from "../../src/auth/tokenStore";
import { fakeApi, type Reply, type Sent } from "./fakeApi";

const EMAIL = "owner@vashi.example";
const PASSWORD = "seven lamps under a bridge";

let sent: Sent[];
let reply: (path: string, ...answers: Reply[]) => void;

beforeEach(() => {
  resetSessionForTests();
  window.history.replaceState(null, "", "/signup");
  ({ sent, reply } = fakeApi());
});

afterEach(() => vi.unstubAllGlobals());

const SIGNUP = "/api/v1/auth/signup";
const REFRESH = "/api/v1/auth/refresh";
const VERIFY = "/api/v1/auth/signup/verify";
const STATES = "/api/v1/refdata/state-codes"; // the onboarding screen loads its state picker
const VERIFIED = { status: 200, body: { access_token: "tok-1", expires_in: 3600, user: { id: "u1", email: EMAIL } } };

async function stepOne(password = PASSWORD) {
  reply(SIGNUP, { status: 202, body: { status: "code_sent" } });
  fireEvent.change(screen.getByLabelText("Work email"), { target: { value: EMAIL } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: password } });
  fireEvent.click(screen.getByRole("button", { name: "Email me a code" }));
  await screen.findByRole("heading", { name: "Check your email" });
}

async function enterCode(code = "123456") {
  fireEvent.paste(screen.getByLabelText("Digit 1 of 6"), { clipboardData: { getData: () => code } });
  fireEvent.click(screen.getByRole("button", { name: "Create account" }));
  await act(async () => {});
}

describe("sign-up", () => {
  it("keeps the email out of the URL and storage, and lands on onboarding with the token in memory", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    render(<App />);
    await stepOne();

    expect(window.location.pathname).toBe("/signup");
    expect(window.location.search).toBe("");
    expect(window.location.href).not.toContain("vashi");
    expect(window.history.state.usr.email).toBe(EMAIL);
    expect(screen.queryByLabelText("Password")).toBeNull(); // still in memory, not asked again

    reply(VERIFY, VERIFIED);
    await enterCode();
    await screen.findByRole("heading", { name: "Your business and GST" });

    expect(sent.map((s) => s.path).filter((p) => p !== REFRESH && p !== STATES)).toEqual([SIGNUP, VERIFY]);
    expect(sent.find((s) => s.path === VERIFY)?.body).toEqual({ email: EMAIL, code: "123456", password: PASSWORD });
    expect(tokenStore.get()).toBe("tok-1");
    expect(window.location.pathname).toBe("/onboarding/business");
    expect(JSON.stringify(window.history.state)).not.toContain(EMAIL);
    expect(setItem).not.toHaveBeenCalled();
    expect(localStorage.length + sessionStorage.length).toBe(0);
  });

  it("asks for the password again after a reload, then finishes [RM41-12]", async () => {
    const first = render(<App />);
    await stepOne();
    first.unmount(); // a reload: history.state survives, component memory doesn't

    render(<App />);
    await screen.findByRole("heading", { name: "Check your email" });
    expect(screen.getByText(/Enter your password again/)).toBeInTheDocument();
    expect(screen.getByText(EMAIL)).toBeInTheDocument();

    await enterCode();
    expect(screen.getByText("Enter your password.")).toBeInTheDocument();
    expect(sent.filter((s) => s.path === VERIFY)).toHaveLength(0);

    reply(VERIFY, VERIFIED);
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: PASSWORD } });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));
    await screen.findByRole("heading", { name: "Your business and GST" });
    expect(sent.filter((s) => s.path === VERIFY).at(-1)?.body?.password).toBe(PASSWORD);
  });

  it("goes back to step 1 on a reload with no email in history", async () => {
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Create your account" })).toBeInTheDocument();
  });

  it("shows a weak password's fix inline, under a password field on the code step", async () => {
    render(<App />);
    await stepOne("short");
    reply(VERIFY, {
      status: 422,
      body: { error: { code: "password_weak", message: "weak", field: "password", fix: "Use at least 10 characters." } },
    });
    await enterCode();

    const field = await screen.findByLabelText("Password");
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(field).toHaveAccessibleDescription("Use at least 10 characters.");
  });

  it("shows a refused code under the code boxes", async () => {
    render(<App />);
    await stepOne();
    reply(VERIFY, { status: 400, body: { error: { code: "code_not_accepted", message: "no" } } });
    await enterCode("000000");
    expect(await screen.findByText(/code didn't work/)).toBeInTheDocument();
    expect(screen.getByLabelText("Digit 1 of 6")).toHaveAttribute("aria-invalid", "true");
  });

  it("shows an invalid email inline and a rate limit as minutes", async () => {
    render(<App />);
    reply(SIGNUP, { status: 422, body: { error: { code: "email_invalid", message: "bad", field: "email" } } });
    fireEvent.change(screen.getByLabelText("Work email"), { target: { value: "not-an-email" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: PASSWORD } });
    fireEvent.click(screen.getByRole("button", { name: "Email me a code" }));
    expect(await screen.findByLabelText("Work email")).toHaveAccessibleDescription(/valid email address/);

    reply(SIGNUP, { status: 429, body: { error: { code: "rate_limited", message: "" } }, headers: { "Retry-After": "90" } });
    fireEvent.click(screen.getByRole("button", { name: "Email me a code" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Too many tries. Try again in 2 minutes.");
  });

  it("drops an old code error when a resend is refused (stale error fix)", async () => {
    render(<App />);
    await stepOne();
    reply(VERIFY, { status: 400, body: { error: { code: "code_not_accepted", message: "no" } } });
    await enterCode("000000");
    expect(await screen.findByText(/code didn't work/)).toBeInTheDocument();

    reply(SIGNUP, { status: 429, body: { error: { code: "rate_limited", message: "" } }, headers: { "Retry-After": "300" } });
    fireEvent.click(screen.getByRole("button", { name: "Send a new code" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Too many tries. Try again in 5 minutes.");
    expect(screen.queryByText(/code didn't work/)).toBeNull();
  });

  it("shows the password rules on step 1", () => {
    render(<App />);
    expect(screen.getByLabelText("Password")).toHaveAccessibleDescription(/At least 10 characters/);
  });

  it("sends a new code and restarts the countdown", async () => {
    render(<App />);
    await stepOne();
    reply(SIGNUP, { status: 202, body: { status: "code_sent" } });
    fireEvent.click(screen.getByRole("button", { name: "Send a new code" }));
    expect(await screen.findByText(/We sent a new code/)).toBeInTheDocument();
    expect(sent.filter((s) => s.path === SIGNUP)).toHaveLength(2);
    expect(screen.getByText(/Code expires in (10:00|9:5\d)/)).toBeInTheDocument();
  });
});

it("shows the not-found page for an unknown path", async () => {
  window.history.replaceState(null, "", "/nope");
  render(<App />);
  expect(await screen.findByRole("heading", { name: "We couldn't find that page" })).toBeInTheDocument();
});
