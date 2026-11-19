import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { fakeApi } from "./fakeApi";

vi.mock("../../src/features", () => ({ FEATURES: { invoicing: true } })); // R2 screens

const B = "/api/v1/b/b-1";
const me = (role = "owner") => ({ status: 200, body: { businesses: [{ business_id: "b-1", display_name: "Vashi Essentials", gstin: null, role }] } });
const profile = (business_type: string | null) => ({ status: 200, body: { business_id: "b-1", business_type, version: 7 } });
const row = (over: Record<string, unknown> = {}) => ({
  product_id: "p-1", code: "AVG", name: "Aloe Vera Gel", uqc: "PCS", status: "active", sale_rate: "120.00", price_needed: false, on_hand: "12.000", no_stock: false, ...over,
});

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

describe("stock", () => {
  it("shows on hand, a No stock note, and the price per 1 qty from the server", async () => {
    server.reply(`${B}/profile`, profile("retail"));
    server.reply(`${B}/stock`, { status: 200, body: { items: [row(), row({ product_id: "p-2", code: "SOAP", name: "Soap", sale_rate: "45.00", on_hand: "-2.000", no_stock: true })], has_more: false } });
    open("/b/b-1/stock");
    expect(await screen.findByText("Aloe Vera Gel")).toBeInTheDocument();
    expect(screen.getByText("12.000 PCS")).toBeInTheDocument();
    expect(screen.getByText("₹120.00")).toBeInTheDocument();
    expect(screen.getAllByText("No stock")).toHaveLength(2); // the filter button and the row note
    expect(screen.getByText(/-2.000 PCS/)).toBeInTheDocument();
  });

  it("asks for the business type first", async () => {
    server.reply(`${B}/profile`, profile(null));
    open("/b/b-1/stock");
    expect(await screen.findByRole("heading", { name: "First, what kind of business is this?" })).toBeInTheDocument();
    expect(server.paths()).not.toContain(`${B}/stock`);
  });

  it("filters by Price needed through the server and saves a price with the product's version", async () => {
    server.reply(`${B}/profile`, profile("distributor"));
    server.reply(`${B}/stock`, { status: 200, body: { items: [row()], has_more: false } });
    open("/b/b-1/stock");
    await screen.findByText("Aloe Vera Gel");
    server.reply(`${B}/stock`, { status: 200, body: { items: [row({ sale_rate: "0.00", price_needed: true })], has_more: false } });
    fireEvent.click(screen.getByRole("button", { name: "Price needed" }));
    const box = await screen.findByLabelText(/Price per 1 PCS/);
    expect(server.sent.filter((s) => s.path === `${B}/stock`).at(-1)!.url).toContain("only=price_needed");
    fireEvent.change(box, { target: { value: "99.5x" } });
    expect(box).toHaveValue("99.5x"); // kept as typed, and said to be wrong
    expect(screen.getByText("Enter a number, like 45 or 45.50.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save price" }));
    expect(server.sent.some((s) => s.method === "PATCH")).toBe(false);
    fireEvent.change(box, { target: { value: "99.5" } });
    server.reply(`GET ${B}/products/p-1`, { status: 200, body: { id: "p-1", version: 4 } });
    server.reply(`PATCH ${B}/products/p-1`, { status: 200, body: { id: "p-1", version: 5 } });
    server.reply(`${B}/stock`, { status: 200, body: { items: [], has_more: false } });
    fireEvent.click(screen.getByRole("button", { name: "Save price" }));
    await screen.findByText("No products match.");
    const patch = server.sent.find((s) => s.method === "PATCH")!;
    expect(patch.headers.get("If-Match")).toBe("4");
    expect(patch.body).toEqual({ sale_rate: "99.5" });
  });

  it("hides the price box from a role that cannot edit the catalog", async () => {
    server.reply(`${B}/profile`, profile("retail"));
    server.reply(`${B}/stock`, { status: 200, body: { items: [row({ sale_rate: "0.00", price_needed: true })], has_more: false } });
    open("/b/b-1/stock", "ca");
    expect(await screen.findByText("Price needed")).toBeInTheDocument();
    expect(screen.queryByLabelText(/Price per 1 PCS/)).toBeNull();
  });
});
