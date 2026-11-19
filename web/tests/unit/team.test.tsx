import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { fakeApi } from "./fakeApi";

const B = "/api/v1/b/b-1";
const me = (role = "owner") => ({ status: 200, body: { businesses: [{ business_id: "b-1", display_name: "Vashi Essentials", gstin: null, role }] } });
const member = (over: Record<string, unknown> = {}) => ({ user_id: "u-1", name: "Asha", email: "asha@example.com", role: "owner", status: "active", can_do: ["Everything"], ...over });
const team = (members: unknown[], invites: unknown[] = []) => ({ status: 200, body: { members, invites } });
const invite = (over: Record<string, unknown> = {}) => ({ id: "i-1", email: "ravi@example.com", role: "billing", status: "pending", expires_at: "2026-11-25T10:00:00Z", ...over });

let server: ReturnType<typeof fakeApi>;
beforeEach(() => {
  resetSessionForTests();
  server = fakeApi();
  server.reply("/api/v1/auth/refresh", { status: 200, body: { access_token: "t", expires_in: 3600 } });
});
afterEach(() => vi.unstubAllGlobals());
const open = (path: string, role = "owner") => {
  server.reply("/api/v1/me/businesses", me(role), me(role));
  window.history.replaceState(null, "", path);
  render(<App />);
};

describe("your team", () => {
  it("lists members and invitations, and sends an invitation by email with a role and one key", async () => {
    server.reply(`${B}/members`, team([member(), member({ user_id: "u-2", name: "Ravi", email: "r@example.com", role: "billing" })], [invite()]));
    open("/b/b-1/settings/team");
    expect(await screen.findByText("Asha")).toBeInTheDocument();
    expect(screen.getByText(/ravi@example.com · Billing · Waiting/)).toBeInTheDocument();
    expect(screen.queryByText(/copy/i)).toBeNull(); // mail only: no copy-link option
    expect(screen.getByText("Enter an email and choose a role to send the invitation.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "ca@example.com" } });
    expect(screen.getByRole("button", { name: "Send invitation" })).toBeDisabled();
    expect(screen.getByText("Choose a role to send the invitation.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Role"), { target: { value: "ca" } });
    server.reply(`POST ${B}/invitations`, { status: 201, body: invite({ id: "i-2", email: "ca@example.com", role: "ca" }) });
    server.reply(`${B}/members`, team([member()], [invite({ id: "i-2", email: "ca@example.com", role: "ca" })]));
    fireEvent.click(screen.getByRole("button", { name: "Send invitation" }));
    expect(await screen.findByText("Invitation sent to ca@example.com.")).toBeInTheDocument();
    const sent = server.sent.find((s) => s.method === "POST" && s.path === `${B}/invitations`)!;
    expect(sent.body).toEqual({ email: "ca@example.com", role: "ca" });
    expect(sent.headers.get("Idempotency-Key")).toBeTruthy();
  });

  it("after a failed send keeps the same key, and starts a fresh one when the server says it belonged to another request", async () => {
    server.reply(`${B}/members`, team([member()]));
    open("/b/b-1/settings/team");
    await screen.findByText("Asha");
    const mismatch = { status: 409, body: { error: { code: "idempotency_mismatch", message: "This Idempotency-Key was already used for a different request" } } };
    server.reply(`POST ${B}/invitations`, { status: 503 }, mismatch, { status: 201, body: invite({ id: "i-2", email: "ca@example.com", role: "ca" }) });
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "ca@example.com" } });
    fireEvent.change(screen.getByLabelText("Role"), { target: { value: "ca" } });
    const posts = () => server.sent.filter((s) => s.method === "POST" && s.path === `${B}/invitations`);
    const press = async (n: number) => {
      fireEvent.click(screen.getByRole("button", { name: "Send invitation" }));
      await vi.waitFor(() => expect(posts()).toHaveLength(n));
      await screen.findByRole("alert");
    };
    await press(1);
    await press(2);
    fireEvent.click(screen.getByRole("button", { name: "Send invitation" }));
    expect(await screen.findByText("Invitation sent to ca@example.com.")).toBeInTheDocument();
    const [a, b, c] = posts();
    expect(b.headers.get("Idempotency-Key")).toBe(a.headers.get("Idempotency-Key"));
    expect(c.headers.get("Idempotency-Key")).not.toBe(b.headers.get("Idempotency-Key"));
  });

  it("shows the server's words when the address is already a member", async () => {
    server.reply(`${B}/members`, team([member()]));
    open("/b/b-1/settings/team");
    await screen.findByText("Asha");
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "asha@example.com" } });
    fireEvent.change(screen.getByLabelText("Role"), { target: { value: "admin" } });
    server.reply(`POST ${B}/invitations`, { status: 422, body: { error: { code: "already_member", message: "This person is already a member", field: "email" } } });
    fireEvent.click(screen.getByRole("button", { name: "Send invitation" }));
    expect(await screen.findByText("This person is already a member")).toBeInTheDocument();
  });

  it("resends and cancels a waiting invitation", async () => {
    server.reply(`${B}/members`, team([member()], [invite()]));
    open("/b/b-1/settings/team");
    await screen.findByText(/ravi@example.com/);
    server.reply(`POST ${B}/invitations/i-1/resend`, { status: 200, body: invite() });
    server.reply(`${B}/members`, team([member()], [invite()]));
    fireEvent.click(screen.getByRole("button", { name: "Resend the invitation to ravi@example.com" }));
    await vi.waitFor(() => expect(server.paths()).toContain(`${B}/invitations/i-1/resend`));
    server.reply(`POST ${B}/invitations/i-1/cancel`, { status: 200, body: invite({ status: "cancelled" }) });
    server.reply(`${B}/members`, team([member()], [invite({ status: "cancelled" })]));
    fireEvent.click(screen.getByRole("button", { name: "Cancel the invitation to ravi@example.com" }));
    expect(await screen.findByText(/ravi@example.com · Billing · Cancelled/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Resend the invitation/ })).toBeNull();
  });

  it("changes a role among the fixed roles, and offers no role change for a CA", async () => {
    server.reply(`${B}/members`, team([member(), member({ user_id: "u-2", name: "Ravi", email: "r@example.com", role: "billing" }), member({ user_id: "u-3", name: "Meera", email: "m@example.com", role: "ca" })]));
    open("/b/b-1/settings/team");
    await screen.findByText("Ravi");
    expect(screen.getByText("A CA's role changes only through a new invitation.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Role for Meera")).toBeNull();
    fireEvent.change(screen.getByLabelText("Role for Ravi"), { target: { value: "admin" } });
    server.reply(`PATCH ${B}/members/u-2`, { status: 200, body: member({ user_id: "u-2", role: "admin" }) });
    server.reply(`${B}/members`, team([member(), member({ user_id: "u-2", name: "Ravi", role: "admin" })]));
    fireEvent.click(within(screen.getByText("Ravi").closest("li")!).getByRole("button", { name: "Save role" }));
    await vi.waitFor(() => expect(server.sent.find((s) => s.method === "PATCH")?.body).toEqual({ role: "admin" }));
  });

  it("deactivates with a reason", async () => {
    server.reply(`${B}/members`, team([member(), member({ user_id: "u-2", name: "Ravi", role: "billing" })]));
    open("/b/b-1/settings/team");
    await screen.findByText("Ravi");
    fireEvent.click(screen.getByRole("button", { name: "Deactivate Ravi" }));
    expect(screen.getByRole("button", { name: "Deactivate" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Why are you deactivating them?"), { target: { value: "Left the company" } });
    server.reply(`POST ${B}/members/u-2/deactivate`, { status: 200, body: member({ user_id: "u-2", status: "deactivated" }) });
    server.reply(`${B}/members`, team([member(), member({ user_id: "u-2", name: "Ravi", status: "deactivated", deactivation_reason: "Left the company" })]));
    fireEvent.click(screen.getByRole("button", { name: "Deactivate" }));
    expect(await screen.findByText(/Left the company/)).toBeInTheDocument();
    expect(server.sent.find((s) => s.path === `${B}/members/u-2/deactivate`)!.body).toEqual({ reason: "Left the company" });
  });

  it("an admin cannot change or deactivate an owner", async () => {
    server.reply(`${B}/members`, team([member(), member({ user_id: "u-2", name: "Ravi", role: "billing" })]));
    open("/b/b-1/settings/team", "admin");
    await screen.findByText("Ravi");
    const owner = screen.getByText("Asha").closest("li")!;
    expect(within(owner).queryByRole("button")).toBeNull();
    expect(screen.getByLabelText("Role for Ravi")).toBeInTheDocument();
  });

  it("is the no-access page for billing and CA", async () => {
    open("/b/b-1/settings/team", "billing");
    expect(await screen.findByText(/You don't have access to this page/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to Home" })).toHaveAttribute("href", "/b/b-1/home");
    expect(screen.queryByText("Go to sign-in")).toBeNull();
    expect(server.paths()).not.toContain(`${B}/members`);
  });
});

describe("accepting an invitation", () => {
  it("asks a signed-out visitor to sign in first, and comes back to the link", async () => {
    server = fakeApi(); // no session: the refresh is refused
    window.history.replaceState(null, "", "/invite/tok-1");
    render(<App />);
    const link = await screen.findByRole("link", { name: "Sign in" });
    expect(link).toHaveAttribute("href", "/signin?next=%2Finvite%2Ftok-1");
    expect(screen.getByRole("link", { name: "Create an account" })).toHaveAttribute("href", "/signup");
  });

  it("shows who invited you, and accepts into the business", async () => {
    server.reply("/api/v1/me/invitations/tok-1", { status: 200, body: { business_name: "Vashi Essentials", role: "ca", inviter_name: "Asha", expires_at: "2026-11-25T10:00:00Z" } });
    server.reply("/api/v1/me/businesses", me("ca"), me("ca"));
    server.reply("POST /api/v1/me/invitations/tok-1/accept", { status: 200, body: { business_id: "b-1" } });
    server.reply("/api/v1/b/b-1/home", { status: 500 });
    window.history.replaceState(null, "", "/invite/tok-1");
    render(<App />);
    expect(await screen.findByText(/Asha invited you to join/)).toBeInTheDocument();
    expect(screen.getByText("Vashi Essentials")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Accept the invitation" }));
    await vi.waitFor(() => expect(window.location.pathname).toBe("/b/b-1/home"));
  });

  it("says plainly when the invitation is not for this account", async () => {
    server.reply("/api/v1/me/invitations/tok-2", { status: 404, body: { error: { code: "not_found", message: "" } } });
    window.history.replaceState(null, "", "/invite/tok-2");
    render(<App />);
    expect(await screen.findByText(/isn't available to this account/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Accept the invitation" })).toBeNull();
  });
});
