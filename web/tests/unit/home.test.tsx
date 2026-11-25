import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { greeting } from "../../src/screens/home/HomePage";
import { formatDate } from "../../src/format/dates";
import { screenPath } from "../../src/screens/home/links";
import { SETUP, daysUntil, dueWords, nextStep, timeline, type Gstr1Build } from "../../src/screens/home/nextStep";
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

const RETURNS = "/api/v1/b/b-1/returns";
const ret = (form: string, over: Record<string, unknown> = {}) => ({
  instance_id: `${form}-1`, form, period: "2026-11", period_label: "November 2026", period_start: "2026-11-01", period_end: "2026-11-30",
  due_date: "2026-12-11", due_date_confirmed: false, due_date_source_url: null, arn: null, filed_on: null, status: "open", ...over,
});
const returns = (...rows: unknown[]) => ({ status: 200, body: { fy: "2026-27", gstin: null, filing_frequency: "monthly", returns: rows } });
const allSet = home({
  checklist: {
    done: 5,
    total: 6,
    items: [
      item("business_profile", true, "settings/company"),
      item("filing_frequency", true, "settings/filing"),
      item("marketplaces", true, "onboarding/marketplaces"),
      item("first_product", true, "products"),
      item("first_customer", true, "customers"),
      item("invite_ca_or_teammate", false, "settings/team"),
    ],
  },
});
const finding = (code: string, level = "block") => ({ code, level, accepted: false, message: "", needs_ca_check: false, source_refs: [], subject_fp: code });
const build = (over: Record<string, unknown> = {}) => ({ status: 200, body: { members_count: 41, line_items: 60, findings: [], export: { ready: true, reasons: [], to_accept: 0 }, ...over } });
const asRole = (role: string) => {
  server = fakeApi(); // a fresh one, so the queued owner answer from beforeEach isn't used
  server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
  server.reply(ME, { status: 200, body: { businesses: [{ business_id: "b-1", display_name: "Vashi Essentials", gstin: null, role }] } });
};
const card = () => screen.findByRole("region", { name: /Finish setting up|GSTR-1 file ready|Nothing is waiting/ });

describe("Home", () => {
  it("greets by name and shows the setup path as the next step, with one button for the current step", async () => {
    server.reply(HOME, home());
    open();
    expect(await screen.findByRole("heading", { level: 1, name: /Welcome, Asha/ })).toBeInTheDocument();
    const next = await screen.findByRole("region", { name: "Finish setting up your business" });
    expect(within(next).getByText("Your next step")).toBeInTheDocument();
    expect(within(next).getByText("Step 3 of 6")).toBeInTheDocument();
    expect(within(next).getByText("Business details").closest("li")).toHaveClass("done");
    expect(within(next).getByText("Marketplaces you sell on").closest("li")).toHaveClass("cur");
    expect(within(next).getByText("Add your first product").closest("li")).toHaveClass("todo");
    expect(within(next).getAllByRole("link")).toHaveLength(1); // one button, nothing else to click in the card
    expect(within(next).getByRole("link", { name: /Choose your marketplaces/ })).toHaveAttribute("href", "/b/b-1/onboarding/marketplaces");
    expect(within(next).getByRole("link", { name: /Choose your marketplaces/ })).toHaveClass("btn-primary");
  });

  it("has dropped the old link boxes: the sidebar is the way round now", async () => {
    server.reply(HOME, home());
    open();
    await card();
    for (const name of ["Products and customers", "Sell", "Business setup", "GST filing"]) expect(screen.queryByRole("navigation", { name })).toBeNull();
  });

  it("moves on to the GSTR-1 path once setup is done, even with the optional invite left", async () => {
    server.reply(HOME, allSet);
    server.reply(RETURNS, returns(ret("GSTR1", { status: "filed_locked", period_label: "October 2026", instance_id: "old" }), ret("GSTR1"), ret("GSTR3B")));
    server.reply("/api/v1/b/b-1/returns/GSTR1-1", build({ findings: [finding("B-01"), finding("B-02"), finding("C-08"), finding("W-01", "info")] }));
    open();
    const next = await screen.findByRole("region", { name: "Get your November 2026 GSTR-1 file ready" });
    expect(await within(next).findByText("Step 2 of 5")).toBeInTheDocument(); // the filed October return is skipped
    expect(within(next).getByText("Sales gathered").closest("li")).toHaveClass("done");
    expect(within(next).getByText("41 invoices and notes")).toBeInTheDocument();
    expect(within(next).getByText("2 to fix")).toBeInTheDocument(); // Table 13 is its own step, information needs nothing
    expect(within(next).getByText("Confirm documents issued").closest("li")).toHaveClass("todo");
    expect(within(next).getByRole("link", { name: /Fix 2 things/ })).toHaveAttribute("href", "/b/b-1/filing/GSTR1-1");
    expect(within(next).getByText(/^You file it on the GST portal yourself/)).toBeInTheDocument(); // unconfirmed due date: no date
    expect(server.paths()).not.toContain("/api/v1/b/b-1/returns/GSTR1-1/changes"); // not asked before its step
  });

  it("asks whether the file was made only once the steps before it are done, then points to Mark it filed", async () => {
    server.reply(HOME, allSet);
    server.reply(RETURNS, returns(ret("GSTR1")));
    server.reply("/api/v1/b/b-1/returns/GSTR1-1", build());
    server.reply("/api/v1/b/b-1/returns/GSTR1-1/changes", { status: 200, body: { reference: { purpose: "export", version: 1 }, same: true, difference: {} } });
    open();
    const next = await screen.findByRole("region", { name: /GSTR-1 file ready/ });
    expect(await within(next).findByText("Step 5 of 5")).toBeInTheDocument();
    expect(within(next).getByRole("link", { name: /Mark it filed/ })).toHaveAttribute("href", "/b/b-1/filing/GSTR1-1");
  });

  it("asks for the file again when the return changed after it was made", async () => {
    server.reply(HOME, allSet);
    server.reply(RETURNS, returns(ret("GSTR1")));
    server.reply("/api/v1/b/b-1/returns/GSTR1-1", build());
    server.reply("/api/v1/b/b-1/returns/GSTR1-1/changes", { status: 200, body: { reference: { purpose: "export", version: 1 }, same: false, difference: {} } });
    open();
    const next = await screen.findByRole("region", { name: /GSTR-1 file ready/ });
    expect(await within(next).findByText("Step 4 of 5")).toBeInTheDocument();
    expect(within(next).getByRole("link", { name: /Make the file/ })).toBeInTheDocument();
  });

  it("still gives a way into the return when its build can't be read", async () => {
    server.reply(HOME, allSet);
    server.reply(RETURNS, returns(ret("GSTR1")));
    server.reply("/api/v1/b/b-1/returns/GSTR1-1", { status: 500 });
    open();
    const next = await screen.findByRole("region", { name: /GSTR-1 file ready/ });
    expect(await within(next).findByRole("link", { name: /Open the return/ })).toHaveAttribute("href", "/b/b-1/filing/GSTR1-1");
    expect(within(next).queryByText(/Step \d/)).toBeNull();
  });

  it("draws the month timeline from confirmed due dates only", async () => {
    server.reply(HOME, allSet);
    server.reply(RETURNS, returns(ret("GSTR1", { due_date: "2026-12-11", due_date_confirmed: true }), ret("GSTR3B", { due_date: "2026-12-20", due_date_confirmed: false })));
    open();
    const tl = await screen.findByRole("region", { name: new Date().toLocaleString("en-IN", { month: "long", timeZone: "Asia/Kolkata" }) });
    expect(await within(tl).findByText("GSTR-1 due")).toBeInTheDocument();
    expect(within(tl).getByText(/^11-Dec-2026/)).toBeInTheDocument();
    expect(within(tl).queryByText("GSTR-3B due")).toBeNull(); // not confirmed: not drawn
    expect(within(tl).getByText("Filing for November 2026 · monthly")).toBeInTheDocument();
  });

  it("doesn't ask for the periods when the role can't see returns (it would be refused)", async () => {
    asRole("billing");
    server.reply(HOME, allSet);
    open();
    const next = await screen.findByRole("region", { name: "Nothing is waiting for you" });
    expect(within(next).getByRole("link", { name: /New invoice/ })).toHaveAttribute("href", "/b/b-1/invoices/new");
    expect(server.paths()).not.toContain(RETURNS);
    expect(screen.queryByText(/^Filing for/)).toBeNull();
  });

  it("shows no invoice tabs, and asks for no invoices, for a role that cannot create them", async () => {
    asRole("ca");
    server.reply(HOME, home());
    open();
    await card();
    expect(screen.getByRole("tab", { name: /Needs your attention/ })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Recent invoices" })).toBeNull();
    expect(screen.queryByRole("link", { name: /New invoice/ })).toBeNull();
    expect(server.paths()).not.toContain("/api/v1/b/b-1/drafts");
    expect(server.paths()).not.toContain("/api/v1/b/b-1/documents");
  });

  it("lists recent invoices and drafts in tabs, three rows each, with a link to the whole list", async () => {
    server.reply(HOME, home());
    server.reply("/api/v1/b/b-1/documents", { status: 200, body: { documents: [{ id: "doc-1", doc_number: "PR-0042", doc_date: "2026-12-07", counterparty_name: "Arora Wholesale", doc_total: "8000.40", is_practice: true }], has_more: true } });
    server.reply("/api/v1/b/b-1/drafts", { status: 200, body: { items: [{ id: "d-1", cash_buyer: null, bill_to: { name: "Green Leaf Stores" }, doc_date: null, total: "11800.00", ready: true, updated_at: "2026-12-02T10:00:00Z" }], has_more: false, next_cursor: null } });
    open();
    const attention = await screen.findByRole("region", { name: "Needs your attention" });
    expect(await within(attention).findByText("1 draft invoice not finished")).toBeInTheDocument();
    expect(within(attention).getByRole("link", { name: "Open drafts" })).toHaveAttribute("href", "/b/b-1/drafts");
    fireEvent.click(screen.getByRole("tab", { name: "Recent invoices" }));
    expect(screen.getByRole("link", { name: "PR-0042" })).toHaveAttribute("href", "/b/b-1/documents/doc-1");
    expect(screen.getByText("₹8,000.40")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "All issued invoices" })).toHaveAttribute("href", "/b/b-1/documents");
    fireEvent.click(screen.getByRole("tab", { name: /Drafts/ }));
    expect(screen.getByRole("link", { name: "Green Leaf Stores" })).toHaveAttribute("href", "/b/b-1/invoices/d-1");
    expect(screen.getByRole("link", { name: "All drafts" })).toHaveAttribute("href", "/b/b-1/drafts");
    const asked = server.sent.filter((x) => x.path.endsWith("/documents") || x.path.endsWith("/drafts")).map((x) => new URL(x.url).searchParams.get("limit"));
    expect(asked).toEqual(["3", "3"]);
  });

  it("shows the v16 sidebar with the business tile and a Main nav that marks the current page", async () => {
    server.reply(HOME, home());
    open();
    await screen.findByRole("heading", { level: 1, name: /Welcome, Asha/ });
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).getByRole("link", { name: "Home" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "Your GST filing" })).toHaveAttribute("href", "/b/b-1/filing");
    expect(within(nav).getByRole("link", { name: "Upload your reports" })).toHaveAttribute("href", "/b/b-1/uploads");
    expect(within(nav).getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/b/b-1/settings");
    expect(within(nav).getAllByRole("link", { current: "page" })).toHaveLength(1);
    expect(screen.getByText("VE")).toBeInTheDocument(); // brand tile initials, hidden from the accessibility tree
  });

  it("marks only Your GST filing on the filing page, though GSTR-1 and GSTR-3B fall back to it", async () => {
    open("/b/b-1/filing");
    const nav = await screen.findByRole("navigation", { name: "Main" });
    await waitFor(() => expect(within(nav).getAllByRole("link", { current: "page" })).toHaveLength(1));
    expect(within(nav).getByRole("link", { current: "page" })).toHaveTextContent("Your GST filing");
    expect(within(nav).getByRole("link", { name: "GSTR-1" })).toHaveAttribute("href", "/b/b-1/filing");
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
    expect(within(list).getByText(/Needs action/)).toBeInTheDocument();
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
    expect(await screen.findByRole("heading", { level: 1, name: /Welcome, Asha/ })).toBeInTheDocument();
  });
});

describe("next step and timeline (pure)", () => {
  const items = (done: number) => Object.keys(SETUP).map((key, i) => ({ key, done: i < done, href: `/b/b-1/${key === "first_product" ? "products" : "home"}` }));
  const row = { instance_id: "r-1", period_label: "November 2026", due_date: "2026-12-11", due_date_confirmed: true };
  const b = (over: Partial<Gstr1Build> = {}): Gstr1Build => ({ members_count: 3, findings: [], export: { to_accept: 0 }, ...over });

  it("picks setup while a step that isn't optional is left, and the GSTR-1 path after", () => {
    expect(nextStep({ businessId: "b-1", today: "2026-12-07", checklist: items(3), gstr1: row }).kind).toBe("setup");
    const s = nextStep({ businessId: "b-1", today: "2026-12-07", checklist: items(3) });
    expect([s.current, s.action]).toEqual([3, { label: "Add your first product", to: "/b/b-1/products" }]);
    expect(nextStep({ businessId: "b-1", today: "2026-12-07", checklist: items(5), gstr1: row }).kind).toBe("gstr1");
    expect(nextStep({ businessId: "b-1", today: "2026-12-07", checklist: items(5) }).kind).toBe("clear");
  });

  it("gives a step no link when the server's link isn't one of our screens", () => {
    const s = nextStep({ businessId: "b-1", today: "2026-12-07", checklist: [{ key: "business_profile", done: false, href: "https://evil.example" }] });
    expect(s.action).toBeNull();
  });

  it("walks the GSTR-1 path from the build: no sales, things to fix, Table 13, the file", () => {
    const at = (build: Gstr1Build, fileTaken: boolean | null = null, canUpload = true) => {
      const s = nextStep({ businessId: "b-1", today: "2026-12-07", checklist: [], gstr1: row, build, fileTaken, canUpload });
      return [s.current, s.action?.label];
    };
    expect(at(b({ members_count: 0 }))).toEqual([0, "Upload your reports"]);
    // #406: a month with no sales is not a dead end; the card offers the nil return too.
    const nil = nextStep({ businessId: "b-1", today: "2026-12-07", checklist: [], gstr1: row, build: b({ members_count: 0 }), canUpload: true });
    expect(nil.alt).toEqual({ label: "No sales in November 2026? Go on to a nil return", to: "/b/b-1/filing/r-1" });
    expect(nil.steps[0].sub).toBe("None found yet");
    expect(nextStep({ businessId: "b-1", today: "2026-12-07", checklist: [], gstr1: row, build: b(), canUpload: true }).alt).toBeNull();
    expect(at(b({ members_count: 0 }), null, false)).toEqual([0, "Open the return"]);
    expect(at(b({ export: { to_accept: 1 } }))).toEqual([1, "Fix 1 thing"]);
    expect(at(b({ findings: [{ code: "C-08", level: "block", accepted: false }] }))).toEqual([2, "Confirm documents issued"]);
    expect(at(b())).toEqual([3, "Make the file"]);
    expect(at(b(), true)).toEqual([4, "Mark it filed"]);
  });

  it("says when the return is due only from a confirmed date", () => {
    expect(nextStep({ businessId: "b-1", today: "2026-12-07", checklist: [], gstr1: row }).hint).toMatch(/^Due 11-Dec-2026, in 4 days\./);
    expect(nextStep({ businessId: "b-1", today: "2026-12-07", checklist: [], gstr1: { ...row, due_date_confirmed: false } }).hint).toMatch(/^You file it/);
    expect([dueWords(0), dueWords(1), dueWords(-1), dueWords(-3)]).toEqual(["today", "tomorrow", "1 day ago", "3 days ago"]);
    expect(daysUntil("2027-01-01", "2026-12-31")).toBe(1);
  });

  it("places this month's markers on the track and keeps next month's in the list only", () => {
    const t = timeline("2026-12-07", [
      { form: "GSTR1", due_date: "2026-12-11", due_date_confirmed: true },
      { form: "GSTR3B", due_date: "2027-01-20", due_date_confirmed: true },
    ]);
    expect(t.month).toBe("December");
    expect(t.markers.map((m) => m.key)).toEqual(["today", "GSTR1", "GSTR3B"]);
    expect(t.onTrack.map((m) => m.key)).toEqual(["today", "GSTR1"]);
    expect(t.onTrack[1].at).toBeCloseTo(10 / 30);
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
