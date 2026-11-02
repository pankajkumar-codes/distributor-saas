import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { fakeApi } from "./fakeApi";

const REFRESH = "/api/v1/auth/refresh";
const ME = "/api/v1/me/businesses";
const STATES = "/api/v1/refdata/state-codes";
const LIST = "/api/v1/b/b-1/customers";
const me = { status: 200, body: { businesses: [{ business_id: "b-1", display_name: "Vashi Essentials", gstin: null, role: "owner" }] } };
const states = {
  status: 200,
  body: { on: "2026-11-02", states: [{ code: "19", name: "West Bengal" }, { code: "27", name: "Maharashtra" }, { code: "96", name: "Other Country" }] },
};

const address = (state_code: string | null) => ({ line1: null, line2: null, city: null, pin: null, state_code });
const customer = (over: Record<string, unknown> = {}) => ({
  id: "c-1",
  name: "Sharma Traders",
  gstin: "19AAAAA0000A1Z5",
  gstin_state_code: "19",
  billing: address("19"),
  delivery_same_as_billing: true,
  delivery: null,
  credit_days: 30,
  status: "active",
  version: 1,
  in_use: false,
  warnings: [],
  ...over,
});
const page = (items: unknown[], has_more = false) => ({ status: 200, body: { items, has_more } });

let server: ReturnType<typeof fakeApi>;

beforeEach(() => {
  resetSessionForTests();
  server = fakeApi();
  server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
  server.reply(ME, me);
  server.reply(STATES, states);
});
afterEach(() => vi.unstubAllGlobals());

function open(path = "/b/b-1/customers") {
  window.history.replaceState(null, "", path);
  render(<App />);
}
const queries = () =>
  server.sent.filter((s) => s.path === LIST).map((s) => Object.fromEntries(new URL(s.url).searchParams));

describe("the customers list", () => {
  it("shows each customer's GSTIN, billing state and credit days as the server sends them, with its warnings", async () => {
    server.reply(
      LIST,
      page([
        customer(),
        customer({
          id: "c-2",
          name: "Asha Stores",
          gstin: null,
          gstin_state_code: null,
          billing: address("27"),
          credit_days: 0,
          warnings: [{ code: "billing_state_differs", field: "billing.state_code", message: "Billing state differs from the GSTIN's state" }],
          status: "archived",
        }),
      ]),
    );
    open();
    const sharma = (await screen.findByText("Sharma Traders")).closest("tr")!;
    expect(within(sharma).getByText("19AAAAA0000A1Z5")).toBeInTheDocument();
    expect(await within(sharma).findByText("West Bengal")).toBeInTheDocument();
    expect(within(sharma).getByText("30")).toBeInTheDocument();
    const asha = screen.getByText("Asha Stores").closest("tr")!;
    expect(within(asha).getByText("Unregistered")).toBeInTheDocument();
    expect(within(asha).getByText("Maharashtra")).toBeInTheDocument();
    expect(within(asha).getByText("Billing state differs from the GSTIN's state")).toBeInTheDocument();
    expect(within(asha).getByText("Archived")).toBeInTheDocument();
    expect(queries()[0]).toEqual({ status: "active", limit: "50", offset: "0" });
  });

  it("asks the server for each tab and keeps it in the URL", async () => {
    server.reply(LIST, page([]), page([]));
    open();
    await screen.findByText("No customers yet. Add your first with New customer.");
    fireEvent.click(screen.getByRole("button", { name: "Archived" }));
    await vi.waitFor(() => expect(queries()).toHaveLength(2));
    expect(queries()[1]).toMatchObject({ status: "archived" });
    expect(window.location.search).toBe("?status=archived");
    expect(await screen.findByText("No customers match.")).toBeInTheDocument();
  });

  it("searches by name or GSTIN once typing pauses, and keeps the search in the URL", async () => {
    server.reply(LIST, page([]), page([customer()]));
    open();
    await screen.findByText("No customers yet. Add your first with New customer.");
    fireEvent.change(screen.getByLabelText("Search by name or GSTIN"), { target: { value: "19" } });
    fireEvent.change(screen.getByLabelText("Search by name or GSTIN"), { target: { value: " 19AAAAA " } });
    expect(await screen.findByText("Sharma Traders")).toBeInTheDocument();
    expect(queries().map((q) => q.q)).toEqual([undefined, "19AAAAA"]);
    expect(new URLSearchParams(window.location.search).get("q")).toBe("19AAAAA");
  });

  it("opens on the search and tab in the URL", async () => {
    server.reply(LIST, page([]));
    open("/b/b-1/customers?status=all&q=asha");
    await screen.findByText("No customers match.");
    expect(queries()[0]).toMatchObject({ status: "all", q: "asha" });
    expect(screen.getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("Search by name or GSTIN")).toHaveValue("asha");
  });

  it("loads the next page from where the last one ended", async () => {
    server.reply(LIST, page([customer()], true), page([customer({ id: "c-2", name: "Asha Stores" })]));
    open();
    await screen.findByText("Sharma Traders");
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByText("Asha Stores")).toBeInTheDocument();
    expect(queries()[1]).toMatchObject({ offset: "50" });
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
  });

  it("is NotFound for another business, without asking the server", async () => {
    open("/b/b-9/customers");
    expect(await screen.findByText(/couldn't find that page/i)).toBeInTheDocument();
    expect(server.paths()).not.toContain("/api/v1/b/b-9/customers");
  });
});
