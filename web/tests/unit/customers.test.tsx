import { act, fireEvent, render, screen, within } from "@testing-library/react";
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

describe("the customers list when the server fails", () => {
  it("replaces Loading with a plain message and a working Try again", async () => {
    open(); // nothing queued for the list: every request answers 500
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    // After the first failure it says it is trying again, rather than looking stuck.
    expect(await screen.findByText("Having trouble loading. Trying again…")).toBeInTheDocument();
    expect(await screen.findByText(/Something went wrong on our side/, {}, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.queryByText("Loading…")).toBeNull();
    server.reply(LIST, page([customer()]));
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Sharma Traders")).toBeInTheDocument();
    expect(screen.queryByText(/Something went wrong/)).toBeNull();
  }, 10000);
});

describe("the customers list", () => {
  it("has a breadcrumb and a New customer link (v16 head)", async () => {
    server.reply(LIST, page([]));
    open();
    await screen.findByText(/No customers yet/);
    expect(within(screen.getByRole("navigation", { name: "Breadcrumb" })).getByText("Customers")).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "New customer" })).toHaveAttribute("href", "/b/b-1/customers/new");
  });

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
    expect(within(asha).getByText("None")).toBeInTheDocument();
    expect(within(asha).getByText("Maharashtra")).toBeInTheDocument();
    expect(within(asha).getByText("Billing state differs from the GSTIN's state")).toBeInTheDocument();
    expect(within(asha).getByText("Archived")).toBeInTheDocument();
    expect(queries()[0]).toEqual({ status: "active", limit: "5", offset: "0" });
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

  it("pages five at a time with Previous and Next, and keeps the page in the URL", async () => {
    server.reply(LIST, page([customer()], true), page([customer({ id: "c-2", name: "Asha Stores" })]));
    open();
    await screen.findByText("Sharma Traders");
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("Asha Stores")).toBeInTheDocument();
    expect(screen.queryByText("Sharma Traders")).toBeNull();
    expect(queries()[1]).toMatchObject({ limit: "5", offset: "5" });
    expect(window.location.search).toBe("?page=2");
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
  });

  it("puts the URL's search back in the box when the URL changes, as on Back", async () => {
    server.reply(LIST, page([]), page([]));
    open("/b/b-1/customers?q=sharma");
    await screen.findByText("No customers match.");
    act(() => {
      window.history.pushState(null, "", "/b/b-1/customers?q=asha");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    await vi.waitFor(() => expect(screen.getByLabelText("Search by name or GSTIN")).toHaveValue("asha"));
    await vi.waitFor(() => expect(queries().map((q) => q.q)).toEqual(["sharma", "asha"]));
  });

  it("is NotFound for another business, without asking the server", async () => {
    open("/b/b-9/customers");
    expect(await screen.findByText(/couldn't find that page/i)).toBeInTheDocument();
    expect(server.paths()).not.toContain("/api/v1/b/b-9/customers");
  });
});

describe("the top bar search (mocks v16)", () => {
  it("suggests nothing until a letter is typed, then searches this business's invoices, customers and products", async () => {
    server.reply(LIST, page([]));
    open();
    const box = await screen.findByRole("combobox", { name: "Search invoices, customers and products" });
    expect(box).toHaveAttribute("placeholder", "Search invoices, customers, products");
    const before = server.sent.length;
    fireEvent.focus(box);
    expect(screen.queryByRole("link", { name: /Sharma/ })).toBeNull();
    expect(server.sent.slice(before).filter((s) => s.path.endsWith("/products"))).toHaveLength(0);

    server.reply(LIST, page([customer()]));
    server.reply("/api/v1/b/b-1/products", page([{ id: "p-1", name: "Sharp knife", code: "SK1" }]));
    server.reply("/api/v1/b/b-1/documents", { status: 200, body: { documents: [{ id: "doc-1", doc_number: "PR-0042", counterparty_name: "Sharma Traders", doc_total: "8000.40" }], has_more: false } });
    fireEvent.change(box, { target: { value: "sh" } });
    const pop = await screen.findByRole("region", { name: "Customers" });
    expect(within(pop).getByRole("link", { name: /Sharma Traders/ })).toHaveAttribute("href", "/b/b-1/customers/c-1");
    expect(await screen.findByRole("link", { name: /Sharp knife/ })).toHaveAttribute("href", "/b/b-1/products/p-1");
    const invoices = await screen.findByRole("region", { name: "Invoices" });
    expect(within(invoices).getByRole("link", { name: /PR-0042 Sharma Traders/ })).toHaveAttribute("href", "/b/b-1/documents/doc-1");
    expect(within(invoices).getByText("₹8,000.40")).toBeInTheDocument();
    const searched = server.sent.slice(before).filter((s) => new URL(s.url).searchParams.get("q") === "sh").map((s) => s.path);
    expect(searched.sort()).toEqual(["/api/v1/b/b-1/customers", "/api/v1/b/b-1/documents", "/api/v1/b/b-1/products"]);
  });

  it("leaves invoices out of the search for a role that can't see them (the server would refuse)", async () => {
    server = fakeApi();
    server.reply("/api/v1/auth/refresh", { status: 200, body: { access_token: "t", expires_in: 3600 } });
    server.reply("/api/v1/me/businesses", { status: 200, body: { businesses: [{ business_id: "b-1", display_name: "Vashi Essentials", gstin: null, role: "ca" }] } });
    server.reply(LIST, page([]));
    open();
    const box = await screen.findByRole("combobox", { name: "Search customers and products" });
    server.reply(LIST, page([customer()]));
    server.reply("/api/v1/b/b-1/products", page([]));
    fireEvent.change(box, { target: { value: "sh" } });
    await screen.findByRole("region", { name: "Customers" });
    expect(server.paths()).not.toContain("/api/v1/b/b-1/documents");
  });
});
