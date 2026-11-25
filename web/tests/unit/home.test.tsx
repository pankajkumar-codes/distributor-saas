import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { greeting } from "../../src/screens/home/HomePage";
import { formatDate } from "../../src/format/dates";
import { screenPath } from "../../src/screens/home/links";
import { fakeApi } from "./fakeApi";

const REFRESH = "/api/v1/auth/refresh";
const ME = "/api/v1/me/businesses";
const HOME = "/api/v1/b/b-1/home";
const me = { status: 200, body: { businesses: [{ business_id: "b-1", display_name: "Vashi Essentials", gstin: null, role: "owner" }] } };
const item = (key: string, done: boolean, path: string) => ({ key, done, href: `/b/b-1/${path}` });
const home = (over: Record<string, unknown> = {}) => ({
  status: 200,
  body: {
    greeting_name: "Asha",
    checklist: {
      done: 2,
      total: 6,
      items: [
        item("business_profile", true, "settings/company"),
        item("filing_frequency", true, "settings/filing"),
        item("marketplaces", false, "onboarding/marketplaces"),
        item("first_product", false, "products"),
        item("first_customer", false, "customers"),
        item("invite_ca_or_teammate", false, "settings/team"),
      ],
    },
    filing: null,
    hub: null,
    insights: null,
    attention: [],
    ...over,
  },
});

let server: ReturnType<typeof fakeApi>;

beforeEach(() => {
  resetSessionForTests();
  server = fakeApi();
  server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
  server.reply(ME, me);
});
afterEach(() => vi.unstubAllGlobals());

function open(path = "/b/b-1/home") {
  window.history.replaceState(null, "", path);
  render(<App />);
}

describe("Home", () => {
  it("greets by name and lists the setup steps, with a link for each step that has a screen", async () => {
    server.reply(HOME, home());
    open();
    expect(await screen.findByRole("heading", { level: 1, name: /, Asha$/ })).toBeInTheDocument();
    const setup = screen.getByRole("region", { name: "Set up your business" });
    expect(within(setup).getByText("2 of 6 done")).toBeInTheDocument();
    expect(within(setup).getByText("Business details").closest("li")).toHaveTextContent("(done)");
    expect(within(setup).getByRole("link", { name: "Add your first product" })).toHaveAttribute("href", "/b/b-1/products");
    expect(within(setup).getByRole("link", { name: "Add your first customer" })).toHaveAttribute("href", "/b/b-1/customers");
    expect(within(setup).getByRole("link", { name: "Marketplaces you sell on" })).toHaveAttribute("href", "/b/b-1/onboarding/marketplaces");
    expect(within(setup).getByRole("link", { name: "Invite your CA or a teammate" })).toHaveAttribute("href", "/b/b-1/settings/team");
    expect(within(setup).queryByText("Upcoming")).toBeNull(); // every step has a screen now
    expect(within(setup).getAllByRole("link")).toHaveLength(4); // no dead links
    const settings = screen.getByRole("navigation", { name: "Business setup" });
    expect(within(settings).getByRole("link", { name: "Open Business setup" })).toHaveAttribute("href", "/b/b-1/settings");
    expect(within(settings).getByRole("link", { name: "Support access" })).toHaveAttribute("href", "/b/b-1/settings/support");
  });

  it("shows the GST filing card from the server's periods: confirmed dates only, otherwise points to Filing home", async () => {
    const r = (form: string, over: Record<string, unknown>) => ({
      instance_id: `${form}-1`, form, period: "2026-10", period_label: "October 2026", period_start: "2026-10-01", period_end: "2026-10-31",
      due_date: "2026-11-11", due_date_confirmed: false, due_date_source_url: null, status: "open", ...over,
    });
    server.reply(HOME, home());
    server.reply("/api/v1/b/b-1/returns", {
      status: 200,
      body: { fy: "2026-27", filing_frequency: "monthly", returns: [r("GSTR1", { status: "filed_locked", period_label: "September 2026" }), r("GSTR1", {}), r("GSTR3B", { due_date_confirmed: true })] },
    });
    open();
    const card = await screen.findByRole("navigation", { name: "GST filing" });
    expect(await within(card).findByText("Monthly")).toBeInTheDocument();
    expect(within(card).getByText("GSTR-1 · October 2026")).toBeInTheDocument(); // the filed September row is skipped
    expect(within(card).getByText("Due date: check Filing home")).toBeInTheDocument(); // unconfirmed: no date shown
    expect(within(card).getByText("Due 11-Nov-2026")).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: "Open Filing home" })).toHaveAttribute("href", "/b/b-1/filing");
  });

  it("doesn't ask for the periods when the role can't prepare returns (it would be refused)", async () => {
    server = fakeApi(); // a fresh one, so the queued owner answer from beforeEach isn't used
    server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
    server.reply(ME, { status: 200, body: { businesses: [{ business_id: "b-1", display_name: "Vashi Essentials", gstin: null, role: "billing" }] } });
    server.reply(HOME, home());
    open();
    await screen.findByRole("navigation", { name: "Business setup" });
    expect(screen.queryByRole("navigation", { name: "GST filing" })).toBeNull(); // billing is turned away from filing
    expect(server.paths()).not.toContain("/api/v1/b/b-1/returns");
  });

  it("leaves the Purchase invoices link out of the Sell card for billing, which would be refused", async () => {
    server = fakeApi();
    server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
    server.reply(ME, { status: 200, body: { businesses: [{ business_id: "b-1", display_name: "Vashi Essentials", gstin: null, role: "billing" }] } });
    server.reply(HOME, home());
    open();
    const sell = await screen.findByRole("navigation", { name: "Sell" });
    expect(within(sell).getByRole("link", { name: "New invoice" })).toBeInTheDocument();
    expect(within(sell).queryByRole("link", { name: "Purchase invoices" })).toBeNull();
  });

  it("puts a primary New invoice button at the top, above every card, so it needs no scrolling", async () => {
    server.reply(HOME, home());
    open();
    const buttons = await screen.findAllByRole("link", { name: "New invoice" });
    const top = buttons.find((b) => b.classList.contains("btn-primary"))!;
    expect(top).toHaveAttribute("href", "/b/b-1/invoices/new");
    const firstCard = screen.getByRole("navigation", { name: "Products and customers" });
    expect(top.compareDocumentPosition(firstCard) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("shows no New invoice button to a role that cannot create invoices", async () => {
    server = fakeApi();
    server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
    server.reply(ME, { status: 200, body: { businesses: [{ business_id: "b-1", display_name: "Vashi Essentials", gstin: null, role: "ca" }] } });
    server.reply(HOME, home());
    open();
    await screen.findByRole("navigation", { name: "Products and customers" });
    expect(screen.queryByRole("link", { name: "New invoice" })).toBeNull();
  });

  it("links to Products and Customers from Home for every role", async () => {
    server.reply(HOME, home());
    open();
    const card = await screen.findByRole("navigation", { name: "Products and customers" });
    expect(within(card).getByRole("link", { name: "Products" })).toHaveAttribute("href", "/b/b-1/products");
    expect(within(card).getByRole("link", { name: "Customers" })).toHaveAttribute("href", "/b/b-1/customers");
  });

  it("shows the Purchase invoices link in the Sell card to the owner", async () => {
    server.reply(HOME, home());
    open();
    const sell = await screen.findByRole("navigation", { name: "Sell" });
    expect(within(sell).getByRole("link", { name: "Purchase invoices" })).toHaveAttribute("href", "/b/b-1/purchases");
  });

  it("still shows the GST filing card with its button when the periods can't be loaded", async () => {
    server.reply(HOME, home());
    server.reply("/api/v1/b/b-1/returns", { status: 500, body: { detail: "x" } });
    open();
    const card = await screen.findByRole("navigation", { name: "GST filing" });
    expect(within(card).getByRole("link", { name: "Open Filing home" })).toBeInTheDocument();
    expect(within(card).queryByText(/GSTR-/)).toBeNull();
  });

  it("marks only Your GST filing on the filing page, though GSTR-1 and GSTR-3B fall back to it", async () => {
    open("/b/b-1/filing");
    const nav = await screen.findByRole("navigation", { name: "Main" });
    await waitFor(() => expect(within(nav).getAllByRole("link", { current: "page" })).toHaveLength(1));
    expect(within(nav).getByRole("link", { current: "page" })).toHaveTextContent("Your GST filing");
    expect(within(nav).getByRole("link", { name: "GSTR-1" })).toHaveAttribute("href", "/b/b-1/filing");
  });

  it("shows the v16 sidebar with the business tile and a Main nav that marks the current page", async () => {
    server.reply(HOME, home());
    open();
    await screen.findByRole("heading", { level: 1, name: /, Asha$/ });
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).getByRole("link", { name: "Home" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "Your GST filing" })).toHaveAttribute("href", "/b/b-1/filing");
    expect(within(nav).getByRole("link", { name: "Upload your reports" })).toHaveAttribute("href", "/b/b-1/uploads");
    expect(within(nav).getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/b/b-1/settings");
    expect(within(nav).getAllByRole("link", { current: "page" })).toHaveLength(1);
    expect(screen.getByText("VE")).toBeInTheDocument(); // brand tile initials, hidden from the accessibility tree
  });

  it("hides the checklist once every step is done, and leaves out keys it doesn't know", async () => {
    server.reply(HOME, home({ checklist: { done: 1, total: 1, items: [item("business_profile", true, "x")] } }));
    open();
    await screen.findByRole("heading", { level: 1 });
    await vi.waitFor(() => expect(server.paths()).toContain(HOME));
    expect(screen.queryByRole("region", { name: "Set up your business" })).toBeNull();
  });

  it("shows the attention list, linking only to this business's own screens", async () => {
    server.reply(
      HOME,
      home({
        attention: [
          { key: "return_due", severity: "block", title: "GSTR-1 for October", due: "2026-11-11", href: "/b/b-1/home" },
          { key: "elsewhere", severity: "warn", title: "Outside link", href: "https://evil.example/x" },
          { key: "bad", severity: "loud", title: "Unknown severity" },
        ],
      }),
    );
    open();
    const list = await screen.findByRole("region", { name: "Needs your attention" });
    expect(within(list).getByText("Due 11-Nov-2026")).toBeInTheDocument();
    expect(within(list).getAllByRole("link", { name: "Fix this" })).toHaveLength(1);
    expect(within(list).getByText("Needs action")).toBeInTheDocument();
    expect(within(list).queryByText("Unknown severity")).toBeNull();
  });

  it("is NotFound for a business the user isn't a member of, and doesn't ask the server for it", async () => {
    open("/b/b-9/home");
    expect(await screen.findByText(/couldn't find that page/i)).toBeInTheDocument();
    expect(server.paths()).not.toContain("/api/v1/b/b-9/home");
  });

  it("offers Try again when Home can't load", async () => {
    server.reply(HOME, { status: 503 }, { status: 503 }, { status: 503 }, home());
    open();
    // Two retries back off about 1 s and 2 s first.
    expect(await screen.findByText(/Something went wrong on our side/, {}, { timeout: 6000 })).toBeInTheDocument();
    expect(server.paths().filter((p) => p === HOME)).toHaveLength(3); // two retries, then it stops
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { level: 1, name: /, Asha$/ })).toBeInTheDocument();
  });
});

describe("helpers", () => {
  it("follows a link only to a screen of this business that exists", () => {
    const screens = new Set(["home", "products"]);
    expect(screenPath("/b/b-1/products", "b-1", screens)).toBe("/b/b-1/products");
    expect(screenPath("/b/b-1/products?filter=no_hsn", "b-1", screens)).toBe("/b/b-1/products?filter=no_hsn");
    expect(screenPath("/b/b-1/customers", "b-1", screens)).toBeNull(); // not built yet
    expect(screenPath("/b/b-2/products", "b-1", screens)).toBeNull(); // another business
    expect(screenPath("https://evil.example/b/b-1/products", "b-1", screens)).toBeNull();
    expect(screenPath("//evil.example/b/b-1/products", "b-1", screens)).toBeNull();
    expect(screenPath("/b/b-1/../b-2/products", "b-1", screens)).toBeNull();
    expect(screenPath("/b/b-1//products", "b-1", screens)).toBeNull();
    expect(screenPath("/b/b-1/products\\x", "b-1", screens)).toBeNull();
    expect(screenPath("/b/b-1/pro\nducts", "b-1", screens)).toBeNull();
    expect(screenPath(42, "b-1", screens)).toBeNull();
  });

  it("shows a date it can't read as the server sent it", () => {
    expect(formatDate("2026-11-02")).toBe("02-Nov-2026");
    expect(formatDate("2026-13-02")).toBe("2026-13-02");
    expect(formatDate("2026-00-02")).toBe("2026-00-02");
    expect(formatDate("soon")).toBe("soon");
  });

  it("welcomes by name, or plainly when there is no name", () => {
    expect(greeting(null)).toBe("Welcome");
    expect(greeting("Asha")).toBe("Welcome, Asha");
  });
});

it("doesn't retry a refusal", async () => {
  resetSessionForTests();
  server.reply(HOME, { status: 404, body: { error: { code: "not_found", message: "" } } });
  open();
  await screen.findByText(/That didn't work/);
  expect(server.paths().filter((p) => p === HOME)).toHaveLength(1);
});
