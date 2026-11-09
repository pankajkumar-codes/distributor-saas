import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { fakeApi, type Reply, type Sent } from "./fakeApi";

const EMAIL = "owner@vashi.example";
const PASSWORD = "seven lamps under a bridge";
const RESET = "/api/v1/auth/reset";
const VERIFY = "/api/v1/auth/reset/verify";
const SENT = { status: 202, body: { status: "code_sent", code_ttl_minutes: 15, code_max_tries: 3 } };

let sent: Sent[];
let reply: (path: string, ...answers: Reply[]) => void;

beforeEach(() => {
  resetSessionForTests();
  ({ sent, reply } = fakeApi());
});
afterEach(() => vi.unstubAllGlobals());

function open(path = "/reset") {
  window.history.replaceState(null, "", path);
  render(<App />);
}
async function askForCode() {
  reply(RESET, SENT);
  fireEvent.change(await screen.findByLabelText("Email"), { target: { value: ` ${EMAIL} ` } });
  fireEvent.click(screen.getByRole("button", { name: "Send code" }));
  await screen.findByRole("heading", { name: "Check your email" });
}
async function enter(code = "123456", password = PASSWORD) {
  fireEvent.paste(screen.getByLabelText("Digit 1 of 6"), { clipboardData: { getData: () => code } });
  fireEvent.change(screen.getByLabelText("New password"), { target: { value: password } });
  fireEvent.click(screen.getByRole("button", { name: "Set new password" }));
  await act(async () => {});
}
const to = (path: string) => sent.filter((s) => s.path === path);

describe("forgot password", () => {
  it("is linked from sign-in, carrying the email typed there", async () => {
    open("/signin");
    fireEvent.change(await screen.findByLabelText("Email"), { target: { value: EMAIL } });
    fireEvent.click(screen.getByRole("link", { name: "Forgot your password?" }));
    expect(await screen.findByRole("heading", { name: "Reset your password" })).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toHaveValue(EMAIL);
  });

  it("sends a code, then sets the new password and sends the user to sign in again", async () => {
    open();
    await askForCode();
    expect(to(RESET)[0].body).toEqual({ email: EMAIL });
    expect(window.location.search).toBe(""); // the email stays out of the URL
    expect(screen.getByText(/The code works for 15 minutes\. After 3 wrong tries/)).toBeInTheDocument(); // the server's terms
    expect(screen.getByText(/Code expires in 15:00\./)).toBeInTheDocument();

    reply(VERIFY, { status: 200, body: { status: "password_set" } });
    await enter();
    expect(await screen.findByText(/Your password is changed, and you're signed out everywhere/)).toBeInTheDocument();
    expect(window.location.pathname).toBe("/signin");
    expect(to(VERIFY)[0].body).toEqual({ email: EMAIL, code: "123456", new_password: PASSWORD });
  });

  it("puts a wrong code under the code and a weak password under the password", async () => {
    open();
    await askForCode();
    reply(VERIFY, { status: 400, body: { error: { code: "code_not_accepted", message: "" } } });
    await enter();
    expect(await screen.findByText("That code didn't work. Check it, or send a new code.")).toBeInTheDocument();

    reply(VERIFY, { status: 422, body: { error: { code: "password_weak", message: "the password is too weak", field: "password", fix: "Use at least 10 characters." } } });
    fireEvent.click(screen.getByRole("button", { name: "Set new password" }));
    expect(await screen.findByText("Use at least 10 characters.")).toBeInTheDocument();
    expect(screen.getByLabelText("New password")).toHaveAttribute("aria-invalid", "true");
  });

  it("asks for both before sending anything", async () => {
    open();
    await askForCode();
    fireEvent.click(screen.getByRole("button", { name: "Set new password" }));
    expect(screen.getByText("Choose a new password.")).toBeInTheDocument();
    expect(screen.getByText("Enter all 6 digits.")).toBeInTheDocument();
    expect(to(VERIFY)).toHaveLength(0);
  });

  it("sends a new code with the server's new terms, and goes back with the email kept", async () => {
    open();
    await askForCode();
    reply(RESET, { status: 202, body: { status: "code_sent", code_ttl_minutes: 10, code_max_tries: 5 } });
    fireEvent.click(screen.getByRole("button", { name: "Send a new code" }));
    expect(await screen.findByText("We sent a new code. Earlier codes no longer work.")).toBeInTheDocument();
    expect(screen.getByText(/The code works for 10 minutes\. After 5 wrong tries/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(await screen.findByLabelText("Email")).toHaveValue(EMAIL);
  });

  it("shows a rate limit in words", async () => {
    open();
    reply(RESET, { status: 429, body: { error: { code: "rate_limited", message: "" } } });
    fireEvent.change(await screen.findByLabelText("Email"), { target: { value: EMAIL } });
    fireEvent.click(screen.getByRole("button", { name: "Send code" }));
    expect(await screen.findByRole("heading", { name: "Reset your password" })).toBeInTheDocument();
    await vi.waitFor(() => expect(document.querySelector(".banner, [role=alert]")).not.toBeNull());
    expect(screen.queryByRole("heading", { name: "Check your email" })).toBeNull();
  });
});
