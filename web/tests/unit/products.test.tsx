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
    const rose = screen.getByText("Rose soap").closest("tr")!;
    expect(within(rose).getByText("HSN missing")).toBeInTheDocument();
    expect(within(rose).getByText("Not confirmed")).toBeInTheDocument();
    expect(queries()[0]).toEqual({ status: "active", limit: "50", offset: "0" });
  });

  it("asks the server for each tab and filter, and keeps them in the URL", async () => {
    server.reply(LIST, page([]), page([]), page([]));
    open();
    await screen.findByText(/No products yet/);
    fireEvent.click(screen.getByRole("button", { name: "Archived" }));
    await vi.waitFor(() => expect(queries()).toHaveLength(2));
    fireEvent.click(screen.getByRole("button", { name: "No HSN" }));
    await vi.waitFor(() => expect(queries()).toHaveLength(3));
    expect(queries()[2]).toMatchObject({ status: "archived", filter: "no_hsn" });
    expect(window.location.search).toBe("?status=archived&filter=no_hsn");
    expect(await screen.findByText("No products match.")).toBeInTheDocument();
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

  it("loads the next page from where the last one ended", async () => {
    server.reply(LIST, page([product()], true), page([product({ id: "p-2", name: "Rose soap" })]));
    open();
    await screen.findByText("Neem soap");
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByText("Rose soap")).toBeInTheDocument();
    expect(queries()[1]).toMatchObject({ offset: "50" });
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
  });

  it("puts the URL's search back in the box when the URL changes, and shows each product once", async () => {
    server.reply(LIST, page([product()], true), page([product(), product({ id: "p-2", name: "Rose soap" })]), page([]));
    open("/b/b-1/products?q=neem");
    await screen.findByText("Neem soap");
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    await screen.findByText("Rose soap");
    expect(screen.getAllByText("Neem soap")).toHaveLength(1);
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
