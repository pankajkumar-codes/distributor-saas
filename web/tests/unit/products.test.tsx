import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { formatRate, formatRupees } from "../../src/format/money";
import { fakeApi } from "./fakeApi";

const REFRESH = "/api/v1/auth/refresh";
const ME = "/api/v1/me/businesses";
const LIST = "/api/v1/b/b-1/products";
const me = { status: 200, body: { businesses: [{ business_id: "b-1", display_name: "Vashi Essentials", gstin: null, role: "owner" }] } };

const product = (over: Record<string, unknown> = {}) => ({
  id: "p-1",
  code: "SOAP-1",
  name: "Neem soap",
  hsn: "3401",
  uqc: "NOS",
  sale_rate: "1234567.50",
  barcode: null,
  tax_category: "taxable",
  has_cess: false,
  status: "active",
  version: 1,
  in_use: false,
  rate_on: { rate: "18", rate_id: "r-1", valid_from: "2025-09-22", confirmed: true },
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
});
afterEach(() => vi.unstubAllGlobals());

function open(path = "/b/b-1/products") {
  window.history.replaceState(null, "", path);
  render(<App />);
}

const queries = () =>
  server.sent.filter((s) => s.path === LIST).map((s) => Object.fromEntries(new URL(s.url).searchParams));

describe("the products list", () => {
  it("shows each product's rate and money from the server's strings, with chips", async () => {
    server.reply(LIST, page([product(), product({ id: "p-2", name: "Rose soap", hsn: null, rate_on: { rate: "5", rate_id: "r-2", valid_from: "2025-09-22", confirmed: false } })]));
    open();
    const row = (await screen.findByText("Neem soap")).closest("tr")!;
    expect(within(row).getByText("₹12,34,567.50")).toBeInTheDocument();
    expect(within(row).getByText("18%")).toBeInTheDocument();
    expect(within(row).getByText("—")).toBeInTheDocument(); // no MRP: a dash, never ₹0.00 (#398)
    const rose = screen.getByText("Rose soap").closest("tr")!;
    expect(within(rose).getByText("HSN missing")).toBeInTheDocument();
    expect(within(rose).getByText("Not confirmed")).toBeInTheDocument();
    expect(queries()[0]).toEqual({ status: "active", limit: "5", offset: "0" });
  });

  it("shows a product's MRP from the server's string (#398)", async () => {
    server.reply(LIST, page([product({ mrp: "60.50" })]));
    open();
    const row = (await screen.findByText("Neem soap")).closest("tr")!;
    expect(within(row).getByText("₹60.50")).toBeInTheDocument();
  });

  it("asks the server for each view chip, and keeps it in the URL", async () => {
    server.reply(LIST, page([]), page([]), page([]));
    open();
    await screen.findByText(/No products yet/);
    fireEvent.click(screen.getByRole("button", { name: "Archived" }));
    await vi.waitFor(() => expect(queries()).toHaveLength(2));
    expect(queries()[1]).toMatchObject({ status: "archived" });
    expect(window.location.search).toBe("?view=archived");
    fireEvent.click(screen.getByRole("button", { name: "HSN missing" }));
    await vi.waitFor(() => expect(queries()).toHaveLength(3));
    expect(queries()[2]).toMatchObject({ status: "active", filter: "no_hsn" });
    expect(window.location.search).toBe("?view=no_hsn");
    expect(screen.getByRole("button", { name: "HSN missing" })).toHaveAttribute("aria-pressed", "true");
    expect(await screen.findByText("No products match.")).toBeInTheDocument();
  });

  it("has a breadcrumb and no page of its own to scroll (v16 head)", async () => {
    server.reply(LIST, page([]));
    open();
    await screen.findByText(/No products yet/);
    expect(within(screen.getByRole("navigation", { name: "Breadcrumb" })).getByText("Products")).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "New product" })).toHaveAttribute("href", "/b/b-1/products/new");
    expect(screen.getByRole("link", { name: "Import from a file" })).toHaveAttribute("href", "/b/b-1/products/import");
  });

  it("opens on the filter a Home link names", async () => {
    server.reply(LIST, page([]));
    open("/b/b-1/products?filter=rate_unconfirmed");
    await screen.findByText("No products match.");
    expect(queries()[0]).toMatchObject({ filter: "rate_unconfirmed" });
    expect(screen.getByRole("button", { name: "Rate not confirmed" })).toHaveAttribute("aria-pressed", "true");
  });

  it("searches once typing pauses", async () => {
    server.reply(LIST, page([]), page([product()]));
    open();
    await screen.findByText(/No products yet/);
    fireEvent.change(screen.getByLabelText("Search by name, code or barcode"), { target: { value: "ne" } });
    fireEvent.change(screen.getByLabelText("Search by name, code or barcode"), { target: { value: " neem " } });
    expect(await screen.findByText("Neem soap")).toBeInTheDocument();
    expect(queries().map((q) => q.q)).toEqual([undefined, "neem"]);
  });

  it("pages five at a time with Previous and Next, and keeps the page in the URL", async () => {
    server.reply(LIST, page([product()], true), page([product({ id: "p-2", name: "Rose soap" })]), page([product()], true));
    open();
    await screen.findByText("Neem soap");
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("Rose soap")).toBeInTheDocument();
    expect(screen.queryByText("Neem soap")).toBeNull(); // a page replaces the last one
    expect(queries()[1]).toMatchObject({ limit: "5", offset: "5" });
    expect(window.location.search).toBe("?page=2");
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    expect(await screen.findByText("Neem soap")).toBeInTheDocument();
    expect(window.location.search).toBe("");
  });

  it("goes back to the first page when the search changes", async () => {
    server.reply(LIST, page([product()]), page([product()]));
    open("/b/b-1/products?page=3");
    await screen.findByText("Neem soap");
    expect(queries()[0]).toMatchObject({ offset: "10" });
    fireEvent.change(screen.getByLabelText("Search by name, code or barcode"), { target: { value: "neem" } });
    await vi.waitFor(() => expect(window.location.search).toBe("?q=neem"));
  });

  it("puts the URL's search back in the box when the URL changes", async () => {
    server.reply(LIST, page([product()]), page([]));
    open("/b/b-1/products?q=neem");
    await screen.findByText("Neem soap");
    act(() => {
      window.history.pushState(null, "", "/b/b-1/products?q=rose");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    await vi.waitFor(() => expect(screen.getByLabelText("Search by name, code or barcode")).toHaveValue("rose"));
  });

  it("is NotFound for another business, without asking the server", async () => {
    open("/b/b-9/products");
    expect(await screen.findByText(/couldn't find that page/i)).toBeInTheDocument();
    expect(server.paths()).not.toContain("/api/v1/b/b-9/products");
  });
});

describe("money and rates from strings", () => {
  it("groups the Indian way without passing through a float", () => {
    expect(formatRupees("0")).toBe("₹0.00");
    expect(formatRupees("999.5")).toBe("₹999.50");
    expect(formatRupees("1000")).toBe("₹1,000.00");
    expect(formatRupees("123456.78")).toBe("₹1,23,456.78");
    expect(formatRupees("98765432109876543.21")).toBe("₹98,76,54,32,10,98,76,543.21"); // past Number's precision
    expect(formatRupees("0012.10")).toBe("₹12.10");
    expect(formatRupees("-50")).toBe("-₹50.00");
    expect(formatRupees("-0.00")).toBe("₹0.00"); // no "minus zero"
    expect(formatRupees("12.345")).toBe("12.345"); // would need rounding: shown as sent
    expect(formatRupees("12.3400")).toBe("₹12.34");
    expect(formatRupees("abc")).toBe("abc");
  });

  it("shows a rate as a percentage", () => {
    expect(formatRate("18")).toBe("18%");
    expect(formatRate("0.25")).toBe("0.25%");
  });
});
