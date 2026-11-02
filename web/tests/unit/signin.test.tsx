import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { safeNext } from "../../src/auth/AuthProvider";
import { landingPath } from "../../src/auth/landing";
import { resetSessionForTests } from "../../src/auth/session";
import { tokenStore } from "../../src/auth/tokenStore";
import { fakeApi } from "./fakeApi";

const SIGNIN = "/api/v1/auth/signin";
const TOTP = "/api/v1/auth/signin/totp";
const HOME = /^(Welcome|Good (morning|afternoon|evening))/; // Home's h1 is the greeting
const REFRESH = "/api/v1/auth/refresh";
const ME = "/api/v1/me/businesses";
const EMAIL = "owner@vashi.example";
const A = { business_id: "b-1", display_name: "Vashi Essentials", gstin: "19AAAAA0000A1Z5", role: "owner" };
const B = { business_id: "b-2", display_name: "Second Shop", gstin: null, role: "ca" };
const signedIn = (memberships: unknown[]) => ({
  status: 200,
  body: { access_token: "tok", expires_in: 3600, user: { id: "u1", email: EMAIL }, memberships },
});

let server: ReturnType<typeof fakeApi>;

beforeEach(() => {
  resetSessionForTests();
  server = fakeApi();
});
afterEach(() => vi.unstubAllGlobals());

function open(path: string) {
  window.history.replaceState(null, "", path);
  render(<App />);
}

async function signIn() {
  await screen.findByRole("heading", { name: "Sign in" });
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: EMAIL } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "seven lamps under a bridge" } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

describe("landing after sign-in (LLD-1 §11.2)", () => {
  it("goes to onboarding, the one Home, or the picker", () => {
    expect(landingPath([])).toBe("/onboarding/business");
    expect(landingPath([A])).toBe("/b/b-1/home");
    expect(landingPath([A, B])).toBe("/businesses");
  });

  it("only follows `next` to a path on this site", () => {
    expect(safeNext("/b/b-1/home")).toBe("/b/b-1/home");
    expect(safeNext("//evil.example/x")).toBeNull();
    expect(safeNext("https://evil.example")).toBeNull();
    expect(safeNext("/\\evil.example")).toBeNull();
    expect(safeNext("/b/x\n/home")).toBeNull();
    expect(safeNext("/b/x\u0000")).toBeNull();
    expect(safeNext("/b/x\u007f")).toBeNull();
    expect(safeNext(null)).toBeNull();
  });
});

describe("sign-in", () => {
  it("signs in and lands on the only business's Home, writing nothing to storage", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    open("/signin");
    server.reply(SIGNIN, signedIn([A]));
    server.reply(ME, { status: 200, body: { businesses: [A] } });
    await signIn();
    expect(await screen.findByRole("heading", { name: HOME })).toBeInTheDocument();
    expect(screen.getByText("Vashi Essentials")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/b/b-1/home");
    expect(window.location.href).not.toContain("vashi.example");
    expect(tokenStore.get()).toBe("tok");
    expect(setItem).not.toHaveBeenCalled();
  });

  it("shows the picker for more than one business", async () => {
    open("/signin");
    server.reply(SIGNIN, signedIn([A, B]));
    server.reply(ME, { status: 200, body: { businesses: [A, B] } });
    await signIn();
    expect(await screen.findByRole("link", { name: "Second Shop" })).toHaveAttribute("href", "/b/b-2/home");
  });

  it("returns to `next` after sign-in", async () => {
    open("/signin?next=%2Fbusinesses");
    server.reply(SIGNIN, signedIn([A]));
    server.reply(ME, { status: 200, body: { businesses: [A] } });
    await signIn();
    await screen.findByRole("heading", { name: "Your businesses" });
    expect(window.location.pathname).toBe("/businesses");
  });

  it("says the email or password is wrong without saying which", async () => {
    open("/signin");
    server.reply(SIGNIN, { status: 401, body: { error: { code: "signin_not_accepted", message: "" } } });
    await signIn();
    expect(await screen.findByRole("alert")).toHaveTextContent("The email or password is wrong.");
  });

  it("asks for the authenticator code, retries with the provider's new challenge, then signs in", async () => {
    open("/signin");
    server.reply(SIGNIN, { status: 200, body: { step: "totp", challenge: "ch-1" } });
    await signIn();
    await screen.findByRole("heading", { name: "Two-step sign-in" });
    expect(window.location.pathname).toBe("/signin"); // the challenge is never in the URL

    server.reply(TOTP, { status: 401, body: { error: { code: "totp_not_accepted", message: "" }, challenge: "ch-2" } });
    fireEvent.paste(screen.getByLabelText("Digit 1 of 6"), { clipboardData: { getData: () => "111111" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText(/current code from your authenticator/)).toBeInTheDocument();

    server.reply(TOTP, signedIn([]));
    fireEvent.paste(screen.getByLabelText("Digit 1 of 6"), { clipboardData: { getData: () => "222222" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByRole("heading", { name: "Your business and GST" });

    const tries = server.sent.filter((s) => s.path === TOTP).map((s) => s.body);
    expect(tries).toEqual([
      { email: EMAIL, challenge: "ch-1", code: "111111" },
      { email: EMAIL, challenge: "ch-2", code: "222222" },
    ]);
  });

  it("starts again when the TOTP step expires", async () => {
    open("/signin");
    server.reply(SIGNIN, { status: 200, body: { step: "totp", challenge: "ch-1" } });
    await signIn();
    await screen.findByRole("heading", { name: "Two-step sign-in" });
    server.reply(TOTP, { status: 401, body: { error: { code: "signin_expired", message: "" } } });
    fireEvent.paste(screen.getByLabelText("Digit 1 of 6"), { clipboardData: { getData: () => "111111" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("That took too long. Sign in again.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });
});

describe("a reload", () => {
  it("keeps the session through /auth/refresh", async () => {
    server.reply(REFRESH, { status: 200, body: { access_token: "t-r", expires_in: 3600 } });
    server.reply(ME, { status: 200, body: { businesses: [A] } });
    open("/b/b-1/home");
    expect(await screen.findByRole("heading", { name: HOME })).toBeInTheDocument();
    expect(server.sent.find((s) => s.path === ME)?.headers.get("Authorization")).toBe("Bearer t-r");
  });

  it("goes to sign-in, keeping only the path, when there is no session", async () => {
    open("/b/b-1/home");
    await screen.findByRole("heading", { name: "Sign in" });
    expect(window.location.pathname + window.location.search).toBe("/signin?next=%2Fb%2Fb-1%2Fhome");
  });

  it("offers to try again, without signing out, when refresh can't reach the server", async () => {
    server.reply(REFRESH, { status: 503 }, { status: 200, body: { access_token: "t-r", expires_in: 3600 } });
    server.reply(ME, { status: 200, body: { businesses: [A] } });
    open("/b/b-1/home");
    fireEvent.click(await screen.findByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: HOME })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/b/b-1/home");
  });

  it("goes to sign-in when an API call's session is refused after the retry", async () => {
    server.reply(REFRESH, { status: 200, body: { access_token: "t-r", expires_in: 3600 } }, { status: 401 });
    server.reply(ME, { status: 401, body: { error: { code: "session_invalid", message: "" } } });
    open("/b/b-1/home");
    await screen.findByRole("heading", { name: "Sign in" });
    expect(window.location.search).toBe("?next=%2Fb%2Fb-1%2Fhome");
  });

  it("shows NotFound for a business that isn't in the user's list", async () => {
    server.reply(REFRESH, { status: 200, body: { access_token: "t-r", expires_in: 3600 } });
    server.reply(ME, { status: 200, body: { businesses: [A] } });
    open("/b/someone-elses/home");
    expect(await screen.findByRole("heading", { name: "We couldn't find that page" })).toBeInTheDocument();
  });
});

it("signs out from the top bar", async () => {
  server.reply(REFRESH, { status: 200, body: { access_token: "t-r", expires_in: 3600 } });
  server.reply(ME, { status: 200, body: { businesses: [A] } });
  server.reply("/api/v1/auth/signout", { status: 204 });
  open("/b/b-1/home");
  fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
  await screen.findByRole("heading", { name: "Sign in" });
  expect(server.paths()).toContain("/api/v1/auth/signout");
  expect(tokenStore.get()).toBeNull();
});

it("drops the last user's cached businesses on sign-out, so the next user never sees them", async () => {
  server.reply(REFRESH, { status: 200, body: { access_token: "t-a", expires_in: 3600 } });
  server.reply(ME, { status: 200, body: { businesses: [A] } });
  server.reply("/api/v1/auth/signout", { status: 204 });
  open("/b/b-1/home");
  expect(await screen.findByText("Vashi Essentials")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
  await screen.findByRole("heading", { name: "Sign in" });

  // Someone else signs in, in the same tab, to a business with the same ID.
  const theirs = { ...A, display_name: "Their Shop", gstin: null };
  server.reply(SIGNIN, signedIn([theirs]));
  let release!: () => void;
  const gate = new Promise<void>((r) => (release = r));
  server.reply(ME, { status: 200, body: { businesses: [theirs] }, wait: gate });
  await signIn();
  await waitFor(() => expect(window.location.pathname).toBe("/b/b-1/home"));
  expect(screen.queryByText("Vashi Essentials")).toBeNull(); // nothing from the cache while loading
  release();
  expect(await screen.findByText("Their Shop")).toBeInTheDocument();
  expect(server.paths().filter((p) => p === ME)).toHaveLength(2);
});

it("keeps cached answers through a plain token refresh, and drops them for a new session", async () => {
  const { QueryClient } = await import("@tanstack/react-query");
  const { clearOnSessionChange } = await import("../../src/auth/userCache");
  const { startSession } = await import("../../src/auth/session");
  const client = new QueryClient();
  clearOnSessionChange(client);
  client.setQueryData(["me", "businesses"], [A]);
  startSession("t2", 3600, "refresh");
  expect(client.getQueryData(["me", "businesses"])).toEqual([A]);
  startSession("t3", 3600, "new");
  expect(client.getQueryData(["me", "businesses"])).toBeUndefined();
});
