import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { formatDateTimeIst } from "../../src/format/dates";
import { fakeApi } from "./fakeApi";

const REFRESH = "/api/v1/auth/refresh";
const ME = "/api/v1/me/businesses";
const GRANTS = "/api/v1/b/b-1/support-grants";
const me = (role = "owner") => ({
  status: 200,
  body: { businesses: [{ business_id: "b-1", display_name: "Vashi Essentials", gstin: null, role }] },
});
const PANKAJ = { user_id: "u-1", name: "Pankaj Kumar" };
const grant = (over: Record<string, unknown> = {}) => ({
  id: "g-1",
  given_at: "2026-10-24T08:50:00Z", // 14:20 in India
  expires_at: "2026-10-25T08:50:00Z",
  given_by: PANKAJ,
  reason: "Ticket 1042",
  status: "active",
  ended_at: null,
  ended_by: null,
  pages_viewed: 3,
  ...over,
});
const past = grant({ id: "g-0", given_at: "2026-10-02T05:35:00Z", status: "revoked", ended_at: "2026-10-02T07:10:00Z", ended_by: PANKAJ, reason: null, pages_viewed: 6 });
const list = (...grants: unknown[]) => ({ status: 200, body: { grants } });

let server: ReturnType<typeof fakeApi>;
beforeEach(() => {
  resetSessionForTests();
  server = fakeApi();
  server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
});
afterEach(() => vi.unstubAllGlobals());

function open(role = "owner") {
  server.reply(ME, me(role));
  window.history.replaceState(null, "", "/b/b-1/settings/support");
  render(<App />);
}
const posts = (path: string) => server.sent.filter((s) => s.path === path && s.method === "POST");

describe("support access", () => {
  it("formats instants in India's time", () => {
    expect(formatDateTimeIst("2026-10-24T08:50:00Z")).toBe("24-Oct-2026, 14:20");
    expect(formatDateTimeIst("2026-10-31T19:00:00+00:00")).toBe("01-Nov-2026, 00:30");
    expect(formatDateTimeIst("not a time")).toBe("not a time");
  });

  it("lets an owner give access with a trimmed reason and shows the server's end time", async () => {
    // One path for the list and the POST: replies go in the order the calls are made.
    server.reply(GRANTS, list(past), { status: 201, body: grant() }, list(grant(), past));
    open();
    expect(await screen.findByRole("heading", { name: "No support access right now" })).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(within(table).getByText("02-Oct-2026, 11:05")).toBeInTheDocument();
    expect(within(table).getByText("02-Oct-2026, 12:40 · ended early by Pankaj Kumar")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("What it's for (optional)"), { target: { value: "  Ticket 1042 " } });
    fireEvent.click(screen.getByRole("button", { name: "Give support read-only access" }));
    expect(await screen.findByText(/Support can view your business until 25-Oct-2026, 14:20\./)).toBeInTheDocument();
    expect(posts(GRANTS).map((s) => s.body)).toEqual([{ reason: "Ticket 1042" }]);
    expect(await screen.findByText("On until 25-Oct-2026, 14:20.")).toBeInTheDocument();
    expect(screen.getByText(/Given by Pankaj Kumar on 24-Oct-2026, 14:20 · “Ticket 1042” · 3 pages viewed so far/)).toBeInTheDocument();
  });

  it("ends access now, and a grant that already ended shows the list as it is", async () => {
    server.reply(GRANTS, list(grant()), list(grant({ status: "expired", ended_at: grant().expires_at })));
    server.reply(`${GRANTS}/g-1/revoke`, {
      status: 409,
      body: { error: { code: "grant_ended", message: "This support access has already ended." } },
    });
    open();
    fireEvent.click(await screen.findByRole("button", { name: "End access now" }));
    expect(await screen.findByText("This support access has already ended.")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "No support access right now" })).toBeInTheDocument();
    expect(within(screen.getByRole("table")).getByText("25-Oct-2026, 14:20 · expired")).toBeInTheDocument();
  });

  it("shows an admin the access but no buttons", async () => {
    server.reply(GRANTS, list(grant()));
    open("admin");
    expect(await screen.findByText("On until 25-Oct-2026, 14:20.")).toBeInTheDocument();
    expect(screen.getByText("Only an owner can give or end support access.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "End access now" })).toBeNull();
  });

  it.each(["billing", "ca"])("is not found for %s, and asks the server nothing", async (role) => {
    open(role);
    expect(await screen.findByRole("heading", { name: "We couldn't find that page" })).toBeInTheDocument();
    expect(server.paths()).not.toContain(GRANTS);
  });
});
