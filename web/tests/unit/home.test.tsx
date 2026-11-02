import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { greeting } from "../../src/screens/home/HomePage";
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
  it("greets by name and lists the setup steps, with Coming soon for screens not built yet", async () => {
    server.reply(HOME, home());
    open();
    expect(await screen.findByRole("heading", { level: 1, name: /, Asha$/ })).toBeInTheDocument();
    const setup = screen.getByRole("region", { name: "Set up your business" });
    expect(within(setup).getByText("2 of 6 done")).toBeInTheDocument();
    expect(within(setup).getByText("Business details").closest("li")).toHaveTextContent("(done)");
    expect(within(setup).getByText("Add your first product").closest("a")).toBeNull();
    expect(within(setup).getAllByText("Coming soon")).toHaveLength(4);
    expect(within(setup).queryAllByRole("link")).toHaveLength(0); // no dead links
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

  it("greets by the hour in India", () => {
    expect(greeting(null)).toBe("Welcome");
    expect(greeting("Asha", new Date(Date.UTC(2026, 9, 27, 2)))).toBe("Good morning, Asha"); // 07:30 IST
    expect(greeting("Asha", new Date(Date.UTC(2026, 9, 27, 7)))).toBe("Good afternoon, Asha"); // 12:30 IST
    expect(greeting("Asha", new Date(Date.UTC(2026, 9, 27, 13)))).toBe("Good evening, Asha"); // 18:30 IST
  });
});

it("doesn't retry a refusal", async () => {
  resetSessionForTests();
  server.reply(HOME, { status: 404, body: { error: { code: "not_found", message: "" } } });
  open();
  await screen.findByText(/That didn't work/);
  expect(server.paths().filter((p) => p === HOME)).toHaveLength(1);
});
