import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { resetSessionForTests } from "../../src/auth/session";
import { blankForm, draftIn, formOf, newLine } from "../../src/screens/invoices/draftForm";
import { fakeApi } from "./fakeApi";

vi.mock("../../src/features", () => ({ FEATURES: { invoicing: true } })); // R1 ships with it off

const REFRESH = "/api/v1/auth/refresh";
const ME = "/api/v1/me/businesses";
const STATES = "/api/v1/refdata/state-codes";
const DRAFTS = "/api/v1/b/b-1/drafts";
const ONE = `${DRAFTS}/d-1`;
const mine = (role: string) => ({ status: 200, body: { businesses: [{ business_id: "b-1", display_name: "Vashi Essentials", gstin: null, role }] } });
const states = { status: 200, body: { on: "2026-11-09", states: [{ code: "19", name: "West Bengal" }, { code: "27", name: "Maharashtra" }] } };

const computation = (over: Record<string, unknown> = {}) => ({
  computed_pos: "19", pos_state_code: "19", is_inter_state: false, supply_class: "B2B", lines: [], gross_total: "1000.00", line_discount_total: "0.00",
  invoice_discount: "0.00", charges_total: "0.00", taxable_total: "1000.00", cgst_total: "90.00", sgst_total: "90.00", utgst: false, igst_total: "0.00",
  round_off: "0.00", doc_total: "1180.00", amount_in_words: "Rupees One Thousand One Hundred Eighty only", rounding_mode: "nearest_rupee", method_version: "1",
  blocks: [], warnings: [], ...over,
}); // fmt: skip
const draft = (over: Record<string, unknown> = {}) => ({
  id: "d-1", kind: "invoice", version: 1, customer_id: "c-1", cash_buyer: null, bill_to: { name: "Sharma Traders" }, ship_to: null, doc_date: null,
  invoice_discount: "0.00", charges: [], eway: null, customer_collects: false, ship_to_third_party: false, pos_override: null, pos_override_reason: null,
  lines: [{ id: "l-1", line_no: 1, product_id: "p-1", quantity: "10", unit_price: "100.00", discount_kind: null, discount_value: null }],
  total: "1180.00", ready: true, computed_at: "2026-11-09T10:00:00Z", created_at: "2026-11-09T10:00:00Z", updated_at: "2026-11-09T10:00:00Z", computation: null, ...over,
}); // fmt: skip
const product = { id: "p-1", name: "Aloe Vera Gel 200 ml", hsn: "3304", code: "AVG", sale_rate: "120.00", status: "active", version: 1, warnings: [] };
const customer = { id: "c-1", name: "Sharma Traders", gstin: "19AAAAA0000A1Z5", status: "active", version: 1, warnings: [] };

let server: ReturnType<typeof fakeApi>;
beforeEach(() => {
  resetSessionForTests();
  server = fakeApi();
  server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
  server.reply(ME, mine("owner"));
  server.reply(STATES, states);
});
afterEach(() => vi.unstubAllGlobals());

const open = (path: string) => {
  window.history.replaceState(null, "", path);
  render(<App />);
};
const sent = (path: string, method: string) => server.sent.filter((s) => s.path === path && s.method === method);

describe("a product with no HSN used on an invoice", () => {
  it("links the check to the product, which offers the way back to the invoice", async () => {
    server.reply("/api/v1/b/b-1/products/p-1", { status: 200, body: { ...product, hsn: null, uqc: "NOS", barcode: null, tax_category: "taxable", has_cess: false, in_use: true, rate_on: null, rate_changed_within_warning_window: false, rates: [] } });
    server.reply("/api/v1/b/b-1/units", { status: 200, body: [] });
    const block = { code: "hsn_missing", fix: "Add the product's HSN code.", field: "lines[0].product_id", line_no: 1 };
    server.reply(ONE, { status: 200, body: draft({ computation: computation({ blocks: [block] }) }) });
    open("/b/b-1/invoices/d-1");
    const link = await screen.findByRole("link", { name: "Open the product" });
    expect(link).toHaveAttribute("href", "/b/b-1/products/p-1");
    fireEvent.click(link);
    expect(window.location.pathname).toBe("/b/b-1/products/p-1");
    expect(await screen.findByRole("link", { name: "Back to your invoice" })).toHaveAttribute("href", "/b/b-1/invoices/d-1");
  });
});

describe("a check that needs last year's turnover band", () => {
  it("links to the band field on Business setup, remembering which invoice to come back to", async () => {
    server.reply("/api/v1/b/b-1/products/p-1", { status: 200, body: product });
    const block = { code: "hsn_needs_turnover_band", fix: "Tell us last year's turnover band (FY 2025-26) to use 4-digit HSN codes. Until then, HSN codes need at least 6 digits.", field: "business.turnover_band", line_no: 1 };
    server.reply(ONE, { status: 200, body: draft({ computation: computation({ blocks: [block] }) }) });
    open("/b/b-1/invoices/d-1");
    const link = await screen.findByRole("link", { name: "Set last year's turnover band" });
    expect(link).toHaveAttribute("href", "/b/b-1/settings#last-year-band");
    fireEvent.click(link);
    expect(window.location.pathname).toBe("/b/b-1/settings");
    expect(window.history.state?.usr?.backTo).toBe("/b/b-1/invoices/d-1");
  });

  it("shows the server's fresh checks when the user comes back, so Finalize is no longer held", async () => {
    server.reply("/api/v1/b/b-1/products/p-1", { status: 200, body: product });
    const block = { code: "hsn_needs_turnover_band", fix: "Tell us last year's turnover band (FY 2025-26) to use 4-digit HSN codes.", field: "business.turnover_band", line_no: 1 };
    server.reply(ONE, { status: 200, body: draft({ computation: computation({ blocks: [block] }) }) }, { status: 200, body: draft({ computation: computation() }) });
    open("/b/b-1/invoices/d-1");
    fireEvent.click(await screen.findByRole("link", { name: "Set last year's turnover band" }));
    await waitFor(() => expect(window.location.pathname).toBe("/b/b-1/settings"));
    window.history.back();
    await waitFor(() => expect(window.location.pathname).toBe("/b/b-1/invoices/d-1"));
    await waitFor(() => expect(screen.queryByText(/Tell us last year's turnover band/)).toBeNull());
    expect(screen.getByRole("button", { name: "Create invoice" })).toBeEnabled();
  });

  it("does not offer to leave while there are unsaved edits", async () => {
    server.reply("/api/v1/b/b-1/products/p-1", { status: 200, body: product });
    const block = { code: "hsn_needs_turnover_band", fix: "Tell us last year's turnover band (FY 2025-26) to use 4-digit HSN codes.", field: "business.turnover_band", line_no: 1 };
    server.reply(ONE, { status: 200, body: draft({ computation: computation({ blocks: [block] }) }) });
    open("/b/b-1/invoices/d-1");
    await screen.findByRole("link", { name: "Set last year's turnover band" });
    fireEvent.change(screen.getByLabelText("Quantity"), { target: { value: "11" } });
    expect(screen.queryByRole("link", { name: "Set last year's turnover band" })).toBeNull();
    expect(screen.getByText(/Save your changes first/)).toBeInTheDocument();
  });
});

describe("a check that says the business's own details are missing", () => {
  it("links to Business setup and shows one plain line under Finalize", async () => {
    server.reply("/api/v1/b/b-1/products/p-1", { status: 200, body: product });
    const block = { code: "business_not_ready", fix: "Your business's GSTIN is missing.", field: "business" };
    server.reply(ONE, { status: 200, body: draft({ ready: false, computation: computation({ blocks: [block] }) }) });
    open("/b/b-1/invoices/d-1");
    expect(await screen.findByText(/Your business's GSTIN is missing/)).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Open Business setup" });
    expect(link).toHaveAttribute("href", "/b/b-1/settings");
    expect(screen.getByText("Fix the checks above and save again to finalize.")).toBeInTheDocument();
    expect(screen.queryByText(/After Save draft/)).toBeNull();
  });
});

describe("a cash sale without the buyer's state", () => {
  it("says to choose the state beside the field and sends nothing", async () => {
    server.reply("/api/v1/b/b-1/products/p-1", { status: 200, body: product });
    open("/b/b-1/invoices/new");
    fireEvent.click(await screen.findByLabelText("Cash sale (no GSTIN)"));
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(await screen.findByText("Choose the buyer's state for a cash sale.")).toBeInTheDocument();
    expect(sent(DRAFTS, "POST")).toHaveLength(0);
    expect(screen.getByLabelText("Buyer's state")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("Choose the buyer's state for a cash sale.")).toHaveAttribute("role", "alert");
    expect(document.activeElement).toBe(screen.getByLabelText("Buyer's state")); // focus goes to the field to fix
  });
});

describe("the draft invoice form", () => {
  it("creates a draft once, with the picked customer and product, and shows the server's totals and checks", async () => {
    server.reply("/api/v1/b/b-1/customers", { status: 200, body: { items: [customer], has_more: false } });
    server.reply("/api/v1/b/b-1/products", { status: 200, body: { items: [product], has_more: false } });
    server.reply("/api/v1/b/b-1/products/p-1", { status: 200, body: product });
    server.reply(DRAFTS, { status: 503 }, { status: 201, body: draft({ computation: computation({ blocks: [{ code: "hsn_short", fix: "Add a 6-digit HSN", field: "lines", line_no: 1 }], warnings: [{ code: "rate_unconfirmed", fix: "The rate isn't confirmed with your CA", field: null, line_no: null }] }) }) });
    open("/b/b-1/invoices/new");
    fireEvent.change(await screen.findByLabelText("Find a customer"), { target: { value: "sharma" } });
    fireEvent.click(await screen.findByRole("button", { name: /Sharma Traders · 19AAAAA0000A1Z5/ }, { timeout: 3000 }));
    fireEvent.change(screen.getByLabelText("Add a product"), { target: { value: "aloe" } });
    fireEvent.click(await screen.findByRole("button", { name: /Aloe Vera Gel 200 ml · HSN 3304/ }, { timeout: 3000 }));
    fireEvent.change(screen.getByLabelText("Quantity"), { target: { value: " 10 " } });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(await screen.findByText(/Something went wrong on our side/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(await screen.findByText("Line 1: Add a 6-digit HSN")).toBeInTheDocument();
    expect(screen.getByText("The rate isn't confirmed with your CA")).toBeInTheDocument();
    expect(screen.getByText("₹1,180.00")).toBeInTheDocument();
    const [first, second] = sent(DRAFTS, "POST");
    expect(second.headers.get("Idempotency-Key")).toBe(first.headers.get("Idempotency-Key"));
    expect(second.body).toMatchObject({ kind: "invoice", customer_id: "c-1", cash_buyer: null, ship_to: null, lines: [{ product_id: "p-1", quantity: "10", unit_price: null, discount_kind: null }] });
    expect(await screen.findByRole("heading", { name: "Draft invoice" })).toBeInTheDocument();
    // The blank rate came back filled in by the server; the form shows it, so it is not "changed" and Finalize can be used.
    expect(screen.getByLabelText("Rate (excl. GST)")).toHaveValue("100.00");
    expect(screen.getByRole("button", { name: "Save draft" })).toBeDisabled();
  });

  it("saves a change with the version it opened, and offers their version on a stale save", async () => {
    // GET, then the save (409), then the re-read: the fake answers per path, in order.
    server.reply(
      ONE,
      { status: 200, body: draft() },
      { status: 409, body: { error: { code: "stale_record", message: "stale" } } },
      { status: 200, body: draft({ version: 3, invoice_discount: "5.00" }) },
    );
    server.reply("/api/v1/b/b-1/products/p-1", { status: 200, body: product });
    open("/b/b-1/invoices/d-1");
    expect(await screen.findByText("Sharma Traders")).toBeInTheDocument();
    expect(screen.getByText(/Total as last saved:/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Quantity"), { target: { value: "12" } });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(await screen.findByText(/Someone saved this draft after you opened it/)).toBeInTheDocument();
    expect(sent(ONE, "PUT")[0].headers.get("If-Match")).toBe("1");
    fireEvent.click(screen.getByRole("button", { name: "Load their version" }));
    expect(await screen.findByDisplayValue("5.00")).toBeInTheDocument();
    expect(screen.queryByText(/Someone saved this draft/)).toBeNull();
  });

  it("previews only the saved draft, and links the PDF once it is ready", async () => {
    server.reply(ONE, { status: 200, body: draft() });
    server.reply("/api/v1/b/b-1/products/p-1", { status: 200, body: product });
    server.reply(`${ONE}/preview`, { status: 202, body: { job_id: "j-1", draft_version: 1 } });
    server.reply(`${ONE}/preview/j-1`, { status: 200, body: { status: "ready", url: "https://files.example/p.pdf" } });
    open("/b/b-1/invoices/d-1");
    await screen.findByText("Sharma Traders");
    fireEvent.change(screen.getByLabelText("Quantity"), { target: { value: "11" } });
    expect(screen.getByRole("button", { name: "Preview PDF" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Quantity"), { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: "Preview PDF" }));
    const link = await screen.findByRole("link", { name: "Open the preview (PDF)" });
    expect(link).toHaveAttribute("href", "https://files.example/p.pdf");
    expect(screen.getByText("Draft, not a tax invoice.")).toBeInTheDocument();
  });

  describe("the preview states", () => {
    const PREVIEW = `${ONE}/preview`;
    const opened = async () => {
      server.reply(ONE, { status: 200, body: draft() });
      server.reply("/api/v1/b/b-1/products/p-1", { status: 200, body: product });
      open("/b/b-1/invoices/d-1");
      await screen.findByText("Sharma Traders");
    };
    const press = () => fireEvent.click(screen.getByRole("button", { name: "Preview PDF" }));
    const started = { status: 202, body: { job_id: "j-1", draft_version: 1 } };
    const gone = { status: 401, body: { error: { code: "session_invalid", message: "Sign in" } } };

    it("starts with only the button", async () => {
      await opened();
      expect(screen.getByRole("button", { name: "Preview PDF" })).toBeEnabled();
      expect(screen.queryByText("Preparing the preview…")).toBeNull();
      expect(screen.queryByRole("link", { name: "Open the preview (PDF)" })).toBeNull();
    });

    it("refreshes an expired token during polling and carries on to the link", async () => {
      await opened();
      server.reply(PREVIEW, started);
      server.reply(`${PREVIEW}/j-1`, { status: 200, body: { status: "queued" } }, gone, { status: 200, body: { status: "ready", url: "https://files.example/p.pdf" } });
      server.reply(REFRESH, { status: 200, body: { access_token: "t2", expires_in: 3600 } });
      press();
      expect(await screen.findByText("Preparing the preview…")).toBeInTheDocument();
      expect(await screen.findByRole("link", { name: "Open the preview (PDF)" }, { timeout: 6000 })).toHaveAttribute("href", "https://files.example/p.pdf");
      expect(window.location.pathname).toBe("/b/b-1/invoices/d-1");
    });

    it("says the session ended, keeps the draft on screen, and signs in again back to the same draft", async () => {
      await opened();
      server.reply(PREVIEW, started);
      server.reply(`${PREVIEW}/j-1`, gone);
      server.reply(REFRESH, { status: 503 }); // the refresh could not settle it: the 401 stays
      press();
      expect(await screen.findByText(/Your session has ended\. Your draft is saved\./)).toBeInTheDocument();
      expect(screen.queryByText("Preparing the preview…")).toBeNull();
      expect(screen.getByText("Sharma Traders")).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Sign in again" }));
      await waitFor(() => expect(window.location.pathname).toBe("/signin"));
      expect(window.location.search).toBe(`?next=${encodeURIComponent("/b/b-1/invoices/d-1")}`);
    });

    it("shows an error with Try again when the status cannot be read, instead of staying on Preparing", async () => {
      await opened();
      server.reply(PREVIEW, started, started);
      server.reply(`${PREVIEW}/j-1`, { status: 503 }, { status: 503 }, { status: 503 }, { status: 200, body: { status: "ready", url: "https://files.example/p.pdf" } });
      press();
      expect(await screen.findByText(/Something went wrong on our side/, undefined, { timeout: 6000 })).toBeInTheDocument();
      expect(screen.queryByText("Preparing the preview…")).toBeNull();
      fireEvent.click(screen.getByRole("button", { name: "Try again" }));
      expect(await screen.findByRole("link", { name: "Open the preview (PDF)" })).toBeInTheDocument();
    });

    it("after 30 seconds of preparing says it is slow, and Try again looks again", async () => {
      await opened();
      vi.useFakeTimers({ shouldAdvanceTime: true });
      try {
        server.reply(PREVIEW, started, started);
        server.reply(`${PREVIEW}/j-1`, ...Array.from({ length: 40 }, () => ({ status: 200, body: { status: "rendering" } }))); // the job never finishes
        press();
        expect(await screen.findByText("Preparing the preview…")).toBeInTheDocument();
        await act(async () => {
          vi.advanceTimersByTime(29_000);
        });
        expect(screen.queryByText(/taking longer than usual/)).toBeNull();
        await act(async () => {
          vi.advanceTimersByTime(2_000);
        });
        expect(screen.getByText(/taking longer than usual/)).toBeInTheDocument();
        expect(screen.queryByText("Preparing the preview…")).toBeNull();
        const looks = () => server.sent.filter((x) => x.path === `${PREVIEW}/j-1`).length;
        const before = looks();
        fireEvent.click(screen.getByRole("button", { name: "Try again" }));
        await waitFor(() => expect(looks()).toBeGreaterThan(before));
        expect(sent(PREVIEW, "POST")).toHaveLength(2); // asked again for the same saved version
        expect(screen.queryByText(/taking longer than usual/)).toBeNull(); // and the 30 seconds start over
        expect(screen.getByText("Preparing the preview…")).toBeInTheDocument();
      } finally {
        vi.useRealTimers();
      }
    });
  });

  it("after a save, a customer draft whose server-filled ship-to is the customer's own address is not dirty", async () => {
    const filled = { line1: "12 MG Road", line2: null, city: "Kolkata", pin: "700001", state_code: "19" }; // no "name": the server's copy
    server.reply(ONE, { status: 200, body: draft({ ship_to: filled, computation: computation() }) });
    server.reply("/api/v1/b/b-1/products/p-1", { status: 200, body: product });
    server.reply(`${ONE}/preview`, { status: 202, body: { job_id: "j-1", draft_version: 1 } });
    server.reply(`${ONE}/preview/j-1`, { status: 200, body: { status: "queued" } });
    open("/b/b-1/invoices/d-1");
    await screen.findByText("Sharma Traders");
    expect(screen.getByLabelText("Ship to a different address")).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Save draft" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Preview PDF" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Preview PDF" }));
    expect(await screen.findByText("Preparing the preview…")).toBeInTheDocument();
  });

  it("opens an address the user entered as a different ship-to, with its third-party flag", async () => {
    const own = { name: "Depot", line1: "9 Dock Rd", line2: null, city: "Pune", pin: "411001", state_code: "27" };
    server.reply(ONE, { status: 200, body: draft({ ship_to: own, ship_to_third_party: true }) });
    server.reply("/api/v1/b/b-1/products/p-1", { status: 200, body: product });
    open("/b/b-1/invoices/d-1");
    await screen.findByText("Sharma Traders");
    expect(screen.getByLabelText("Ship to a different address")).toBeChecked();
    expect(screen.getByLabelText("Ship-to name")).toHaveValue("Depot");
    expect(screen.getByLabelText(/Goods go to a third party/)).toBeChecked();
  });

  it("offers no third-party box on a cash sale", async () => {
    open("/b/b-1/invoices/new");
    fireEvent.click(await screen.findByLabelText("Cash sale (no GSTIN)"));
    fireEvent.click(screen.getByLabelText("Ship to a different address"));
    expect(screen.queryByLabelText(/Goods go to a third party/)).toBeNull();
  });

  it("is not there for a role that can't create documents", async () => {
    server = fakeApi();
    server.reply(REFRESH, { status: 200, body: { access_token: "t", expires_in: 3600 } });
    server.reply(ME, mine("ca"));
    server.reply(STATES, states);
    open("/b/b-1/invoices/new");
    expect(await screen.findByRole("heading", { name: "You don't have access to this page" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Find a customer")).toBeNull();
  });
});

describe("the form's body", () => {
  it("sends a cash buyer without a customer, and no ship-to when the customer collects", () => {
    const f = { ...blankForm(), buyer: "cash" as const, customer_id: "c-1", cash_state: "27", cash_name: " ", ship_different: true, customer_collects: true, third_party: true };
    expect(draftIn({ ...f, lines: [{ ...newLine(), product_id: "p-1", quantity: " 2 ", discount_kind: "percent", discount_value: "5" }] })).toMatchObject({
      customer_id: null,
      cash_buyer: { state_code: "27", name: null, address: null },
      ship_to: null,
      ship_to_third_party: false,
      customer_collects: true,
      lines: [{ product_id: "p-1", quantity: "2", unit_price: null, discount_kind: "percent", discount_value: "5" }],
    });
  });

  it("drops a ticked third-party flag when the buyer becomes a cash sale", () => {
    const f = { ...blankForm(), buyer: "cash" as const, cash_state: "27", ship_different: true, third_party: true, ship: { ...blankForm().ship, state_code: "27" } };
    expect(draftIn(f)).toMatchObject({ ship_to_third_party: false });
  });

  it("sends the place-of-supply reason only with an override, and reopens a saved draft as the form it was", () => {
    expect(draftIn({ ...blankForm(), pos_reason: "stray" })).toMatchObject({ pos_override: null, pos_override_reason: null });
    const f = formOf(draft({ pos_override: "27", pos_override_reason: "Delivered in Pune" }) as never, { "p-1": "Gel" });
    expect(f).toMatchObject({ buyer: "customer", customer_name: "Sharma Traders", pos_override: "27", pos_reason: "Delivered in Pune" });
    expect(f.lines[0]).toMatchObject({ key: "l-1", name: "Gel", quantity: "10", unit_price: "100.00" });
  });

  it("never asks for a business type, and saves a draft without one", async () => {
    server.reply(DRAFTS, { status: 201, body: draft() });
    open("/b/b-1/invoices/new");
    fireEvent.change(await screen.findByLabelText("Invoice date"), { target: { value: "2026-11-09" } });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(await screen.findByRole("heading", { name: "Draft invoice" })).toBeInTheDocument();
    expect(screen.queryByText(/business type/i)).toBeNull();
    expect(sent("/api/v1/b/b-1/profile", "GET")).toHaveLength(0);
  });

  it("shows Finalize and why every invoice is a practice one, before anything is saved", async () => {
    open("/b/b-1/invoices/new");
    expect(await screen.findByText(/Practice mode\./)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create invoice" })).toBeEnabled(); // it saves first, then creates
    expect(screen.getByRole("button", { name: "Save draft" })).toBeEnabled();
  });
});
