import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";

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

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

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
  it("gives up on a code request that gets no answer, says so, and lets the button be pressed again", async () => {
    const real = AbortSignal.timeout.bind(AbortSignal);
    const spy = vi.spyOn(AbortSignal, "timeout").mockImplementation(() => real(30));
    onTestFinished(() => spy.mockRestore());
    vi.stubGlobal(
      "fetch",
      vi.fn((input: Request, init?: RequestInit) =>
        new URL(input.url).pathname === REFRESH
          ? Promise.resolve(new Response(null, { status: 401 }))
          : new Promise<Response>((_, reject) => init?.signal?.addEventListener("abort", () => reject(init.signal?.reason))),
      ),
    );
    render(<App />);
    fireEvent.change(screen.getByLabelText("Work email"), { target: { value: EMAIL } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: PASSWORD } });
    const button = screen.getByRole("button", { name: "Email me a code" });
    fireEvent.click(button);
    expect(button).toBeDisabled();
    expect(await screen.findByText("We couldn't reach the server. Check your connection and try again.")).toBeInTheDocument();
    expect(button).toBeEnabled();
  });

  it("tells the person what to do when the code check gets no answer, instead of 'try again'", async () => {
    render(<App />);
    await stepOne();
    const real = AbortSignal.timeout.bind(AbortSignal);
    const spy = vi.spyOn(AbortSignal, "timeout").mockImplementation(() => real(30));
    onTestFinished(() => spy.mockRestore());
    const fetchMock = vi.fn(
      (_input: Request, init?: RequestInit) =>
        new Promise<Response>((_, reject) => init?.signal?.addEventListener("abort", () => reject(init.signal?.reason))),
    );
    vi.stubGlobal("fetch", fetchMock);
    await enterCode();
    expect(await screen.findByText(/send a new code and try again/)).toBeInTheDocument();
    expect(screen.queryByText(/couldn't reach the server/)).not.toBeInTheDocument();
  });

  it("a refresh that hangs on load shows the plain message and a manual retry, and is not retried by itself", async () => {
    window.history.replaceState(null, "", "/onboarding/business");
    const real = AbortSignal.timeout.bind(AbortSignal);
    const spy = vi.spyOn(AbortSignal, "timeout").mockImplementation(() => real(30));
    onTestFinished(() => spy.mockRestore());
    const fetchMock = vi.fn(
      (_input: Request, init?: RequestInit) =>
        new Promise<Response>((_, reject) => init?.signal?.addEventListener("abort", () => reject(init.signal?.reason))),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    expect(await screen.findByText("We couldn't reach the server. Check your connection and try again.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeEnabled();
    await new Promise((r) => setTimeout(r, 150)); // no automatic second attempt with the same cookie
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("keeps a caller's own abort signal working alongside the time limit", async () => {
    const { withAuthTimeout } = await import("../../src/api/timeout");
    const own = new AbortController();
    const joined = withAuthTimeout(own.signal);
    expect(joined.aborted).toBe(false);
    own.abort();
    expect(joined.aborted).toBe(true);
  });

  it("says where the code is in the local demo build only", async () => {
    vi.stubEnv("VITE_DEMO", "1");
    const view = render(<App />);
    expect(screen.getByText(/Local demo: no email is sent/)).toBeInTheDocument();
    view.unmount();
    vi.stubEnv("VITE_DEMO", "");
    render(<App />);
    expect(screen.queryByText(/Local demo/)).not.toBeInTheDocument();
  });

  it("shows plain words, not a generic failure, when the code step is refused", async () => {
    render(<App />);
    await stepOne();
    reply(VERIFY, { status: 401, body: { error: { code: "session_invalid", message: "x" } } });
    await enterCode();
    expect(await screen.findByText("Your session has ended. Sign in again.")).toBeInTheDocument();
  });

  it("explains a refused page address in the local demo only", async () => {
    vi.stubEnv("VITE_DEMO", "1");
    render(<App />);
    await stepOne();
    reply(VERIFY, { status: 401, body: { error: { code: "session_invalid", message: "x" } } });
    await enterCode();
    expect(await screen.findByText(/did not accept the address this page is open at/)).toBeInTheDocument();
  });
});

it("shows the not-found page for an unknown path", async () => {
  window.history.replaceState(null, "", "/nope");
  render(<App />);
  expect(await screen.findByRole("heading", { name: "We couldn't find that page" })).toBeInTheDocument();
});
