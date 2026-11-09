import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { detailText, rowPath } from "../../src/screens/settings/AuditPage";
import { fakeApi } from "./fakeApi";

// Settings › Audit log (LLD-2 §7): the list with its filters and paging, and the CSV export.
const REFRESH = "/api/v1/auth/refresh";
const ME = "/api/v1/me/businesses";
const LOG = "/api/v1/b/b-1/audit-log";
const MEMBERS = "/api/v1/b/b-1/members";
const EXPORTS = "/api/v1/b/b-1/audit-log/exports";
const B = "b-1";
const P = "0b9c5c6e-1c1a-4d1e-9f0a-2a6a0c3e4b5d";
const me = (role = "owner") => ({ status: 200, body: { businesses: [{ business_id: B, display_name: "Vashi Essentials", gstin: null, role }] } });
const row = (over: Record<string, unknown> = {}) => ({
  at: "2026-11-09T08:50:00Z", // 14:20 in India
  actor: { kind: "member", name: "Pankaj Kumar", user_id: "u-1" },
  action: "product.updated",
  action_label: "Edited a product",
  target: { kind: "product", id: P, href: `/b/${B}/products/${P}` },
  reason: null,
  details: { code: "SOAP-1" },
  ...over,
});
const page = (items: unknown[], next_cursor: string | null = null) => ({ status: 200, body: { items, next_cursor } });
const members = {
  status: 200,
  body: { members: [{ user_id: "u-1", name: "Pankaj Kumar", email: "p@example.com", role: "owner", status: "active", can_do: [] }], invites: [] },
};

let server: ReturnType<typeof fakeApi>;
beforeEach(() => {
  resetSessionForTests();
  server = fakeApi();
  server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
});
afterEach(() => vi.unstubAllGlobals());

function open(role = "owner") {
  server.reply(ME, me(role));
  server.reply(MEMBERS, members);
  window.history.replaceState(null, "", `/b/${B}/settings/audit`);
  render(<App />);
}
const gets = (path: string) => server.sent.filter((s) => s.path === path && s.method === "GET");

describe("the audit log", () => {
  it("lists entries newest first, links what exists, and loads more by cursor", async () => {
    server.reply(LOG, page([row(), row({ action: "returns.unlock", action_label: "Unlocked a filed period", reason: "Filed twice", details: {},
      target: { kind: "return_instance", id: "r-1", href: `/b/${B}/returns/r-1` }, actor: { kind: "support", name: "Support team" } })], "c-1"),
      page([row({ action_label: "Started an invoice draft", details: {} })]));
    open();
    const table = await screen.findByRole("table");
    expect(within(table).getByRole("link", { name: "Edited a product" })).toHaveAttribute("href", `/b/${B}/products/${P}`);
    expect(within(table).getByText("Unlocked a filed period").closest("a")).toBeNull(); // no returns screen yet
    expect(within(table).getByText("Filed twice")).toBeInTheDocument();
    expect(within(table).getByText("Support team")).toBeInTheDocument();
    expect(within(table).getAllByText("09-Nov-2026, 14:20")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByText("Started an invoice draft")).toBeInTheDocument();
    expect(new URL(gets(LOG)[1].url).searchParams.get("cursor")).toBe("c-1");
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
  });

  it("sends the filters to the server", async () => {
    server.reply(LOG, page([row()]), page([]));
    open();
    await screen.findByRole("table");
    await screen.findByRole("option", { name: "Pankaj Kumar" });
    fireEvent.change(screen.getByLabelText("Kind"), { target: { value: "invoices" } });
    expect(await screen.findByText("No entries match.")).toBeInTheDocument();
    const sent = new URL(gets(LOG).at(-1)!.url).searchParams;
    expect(sent.get("kind")).toBe("invoices");
    expect(sent.has("actor")).toBe(false);
  });

  it("exports what the filters show and offers the file when it is ready", async () => {
    server.reply(LOG, page([row()]));
    open();
    await screen.findByRole("table");
    server.reply(EXPORTS, { status: 202, body: { job_id: "j-1" } });
    server.reply(`${EXPORTS}/j-1`, { status: 200, body: { status: "ready", url: "https://files.example/a.csv", rows: 12 } });
    fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    const link = await screen.findByRole("link", { name: "Download the CSV" });
    expect(link).toHaveAttribute("href", "https://files.example/a.csv");
    expect(screen.getByText(/12 entries/)).toBeInTheDocument();
    const [post] = server.sent.filter((s) => s.path === EXPORTS && s.method === "POST");
    expect(post.headers.get("idempotency-key")).toBeTruthy();
    expect(post.body).toEqual({});
  });

  it.each([
    [{ status: "failed", error_code: "narrow_filter" }, /too many entries for one file/],
    [{ status: "expired" }, /Export again to get a fresh one/],
  ])("says what to do when the export is %o", async (body, words) => {
    server.reply(LOG, page([]));
    open();
    await screen.findByText("No entries yet.");
    server.reply(EXPORTS, { status: 202, body: { job_id: "j-2" } });
    server.reply(`${EXPORTS}/j-2`, { status: 200, body });
    fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    expect(await screen.findByText(words)).toBeInTheDocument();
  });

  it("is not found for billing (the server would answer 404 too)", async () => {
    open("billing");
    expect(await screen.findByRole("heading", { name: "We couldn't find that page" })).toBeInTheDocument();
    expect(gets(LOG)).toHaveLength(0);
  });
});

describe("row text", () => {
  it("links only screens this app has, for this business", () => {
    expect(rowPath(`/b/${B}/settings/company`, B)).toBe(`/b/${B}/settings/company`);
    expect(rowPath(`/b/${B}/customers/${P}`, B)).toBe(`/b/${B}/customers/${P}`);
    for (const bad of [`/b/b-2/products/${P}`, `/b/${B}/products/${P}/../x`, `/b/${B}/invoices/${P}`, "https://evil.example/", null]) {
      expect(rowPath(bad, B)).toBeNull();
    }
  });

  it("puts the reason first, then the details by name", () => {
    expect(detailText({ reason: "left", details: { role: "billing", code: null } })).toBe("left; role: billing");
    expect(detailText({ reason: null, details: {} })).toBe("");
  });
});
