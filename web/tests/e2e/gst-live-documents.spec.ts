import { expect, test, type Page } from "@playwright/test";

import { noSeriousAxeFindings, signUp } from "./helpers";

// Live documents into GST filing, in a real browser (#480, #482, #484): a West Bengal monthly filer turns on live
// numbering, issues a live B2B invoice, makes a credit note and a debit note by amount on it and cancels a second
// invoice, all from the screens. Then the GSTR-1 for the month shows each one in the right table (B2B, CDNR with its
// note type, HSN, Documents issued) and the GSTR-3B worksheet's 3.1(a) carries the net tax. Needs `sales.finalize.enabled`
// and `sales.finalize.live` on (tests/e2e/enable-finalize.sql, test setup only). Every screen passes axe (no serious or
// critical finding).

const BUYER_GSTIN = "19AABCI1234K1ZN"; // a West Bengal business: intra-state, CGST + SGST

async function createWestBengalMonthly(page: Page) {
  await page.getByLabel("GSTIN").fill("19AAPFU0939F1ZS");
  await page.getByLabel("Legal name (as on GST certificate)").fill("E2E Bengal Traders Private Limited");
  await page.getByLabel("Address line 1").fill("1 Park Street");
  await page.getByLabel("City or town").fill("Kolkata");
  await page.getByLabel("PIN code").fill("700016");
  await page.getByRole("checkbox", { name: "Distributor" }).check();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("group", { name: "Turnover this financial year (declared)" }).getByRole("radio", { name: "Up to the limit for quarterly filing (QRMP)" }).check();
  await page.getByRole("radio", { name: "No", exact: true }).check(); // e-invoicing: never above the limit, so live B2B is allowed (D-113)
  await page.getByRole("checkbox", { name: "Amazon" }).check();
  await page.getByRole("radio", { name: "Monthly" }).check();
  await page.getByRole("button", { name: "Finish and see my filing home" }).click();
  await expect(page).toHaveURL(/\/b\/[0-9a-f-]{36}\/home$/);
  return page.url().match(/\/b\/([0-9a-f-]{36})\//)![1];
}

/** The signed-in user's bearer token, read from the app's own API calls, to seed the catalogue quickly. */
async function bearer(page: Page): Promise<string> {
  const req = page.waitForRequest((r) => r.url().includes("/api/v1/") && !!r.headers()["authorization"]);
  await page.reload();
  return (await req).headers()["authorization"];
}

async function seed(page: Page, businessId: string) {
  const auth = await bearer(page);
  const post = async (path: string, data: object) => {
    const r = await page.request.post(`/api/v1/b/${businessId}${path}`, { data, headers: { authorization: auth, "Idempotency-Key": crypto.randomUUID() } });
    expect(r.status(), await r.text()).toBe(201);
  };
  await post("/customers", { name: "Howrah Wholesale Pvt Ltd", gstin: BUYER_GSTIN, billing: { line1: "5 Station Road", city: "Howrah", pin: "711101", state_code: "19" }, delivery_same_as_billing: true });
  await post("/products", { code: "SOAP18", name: "Neem soap", hsn: "340111", uqc: "NOS", sale_rate: "100.00", mrp: "118.00", tax_category: "taxable", rate: { rate: "18", valid_from: "2025-09-22" } });
}

async function issueInvoice(page: Page, businessId: string, qty: string): Promise<string> {
  await page.goto(`/b/${businessId}/invoices/new`);
  await page.getByLabel("Find a customer").fill("Howrah");
  await page.getByRole("button", { name: "Howrah Wholesale Pvt Ltd" }).click();
  await page.getByLabel("Add a product").fill("Neem");
  await page.getByRole("button", { name: /Neem soap/ }).first().click();
  await page.getByLabel("Quantity of Neem soap").fill(qty);
  await page.getByRole("button", { name: /^Save/ }).click();
  await expect(page.getByRole("heading", { name: "Draft invoice" })).toBeVisible();
  await page.getByRole("button", { name: /^Create invoice/ }).click();
  await expect(page.getByRole("heading", { name: "Invoice issued" })).toBeVisible({ timeout: 15_000 });
  const number = (await page.getByText(/^INV\/\d{2}-\d{2}\/\d{6}$/).first().textContent())!.trim();
  return number;
}

test("live invoice, credit note, debit note and cancel all reach GSTR-1 and the GSTR-3B worksheet", async ({ page }, info) => {
  test.skip(info.project.name.startsWith("phone"), "one walk-through is enough; the phone layout is covered elsewhere");
  test.setTimeout(180_000);
  await signUp(page, `e2e-live-${Date.now()}@example.com`);
  const businessId = await createWestBengalMonthly(page);

  // Settings > Invoice numbering: the owner turns on live numbers.
  await page.goto(`/b/${businessId}/settings/numbering`);
  await expect(page.getByRole("heading", { level: 1, name: "Invoice numbering" })).toBeVisible();
  await noSeriousAxeFindings(page);
  await page.getByRole("button", { name: "Turn on live numbering" }).click();
  await page.getByRole("button", { name: "Yes, turn on live numbering" }).click();
  await expect(page.getByRole("button", { name: "Turn on live numbering" })).toHaveCount(0);
  await seed(page, businessId);

  // A live B2B invoice: 2 x 100.00 at 18%, intra-state.
  const inv1 = await issueInvoice(page, businessId, "2");
  expect(inv1).toMatch(/^INV\/\d{2}-\d{2}\/000001$/);
  await expect(page.getByText("Practice invoice.")).toHaveCount(0);
  await noSeriousAxeFindings(page);
  const inv1Url = page.url();

  // Credit note: one returned, back to stock (taxable 100.00).
  await page.getByRole("link", { name: "Adjust invoice" }).click();
  await expect(page.getByRole("heading", { level: 1, name: /Adjust invoice/ })).toBeVisible();
  await page.getByRole("radio", { name: /Credit note/ }).check();
  await page.getByLabel("Reason").selectOption("goods_returned");
  await page.getByLabel("Quantity to credit, Neem soap").fill("1");
  await noSeriousAxeFindings(page);
  await page.getByRole("button", { name: "Create credit note" }).click();
  await expect(page.getByText(/^CN\/\d{2}-\d{2}\/000001$/).first()).toBeVisible({ timeout: 15_000 });

  // Debit note by amount: 50.00 more taxable value (the case that broke GSTR-1, #480).
  await page.goto(inv1Url);
  await page.getByRole("link", { name: "Adjust invoice" }).click();
  await page.getByRole("radio", { name: /Debit note/ }).check();
  await page.getByLabel("Reason").selectOption("value_too_low");
  await page.getByLabel("Extra taxable value, Neem soap").fill("50");
  await noSeriousAxeFindings(page);
  await page.getByRole("button", { name: "Create debit note" }).click();
  await expect(page.getByText(/^DN\/\d{2}-\d{2}\/000001$/).first()).toBeVisible({ timeout: 15_000 });

  // A second invoice, cancelled: out of the tables, counted in Table 13.
  const inv2 = await issueInvoice(page, businessId, "1");
  await page.getByRole("link", { name: "Adjust invoice" }).click();
  await page.getByRole("radio", { name: /Cancel the invoice/ }).check();
  await page.getByRole("radio", { name: "Raised by mistake" }).check();
  await page.getByRole("checkbox", { name: /were not dispatched/ }).check();
  await noSeriousAxeFindings(page);
  await page.getByRole("button", { name: `Cancel invoice ${inv2}` }).click();
  await expect(page.getByText(/cancelled/i).first()).toBeVisible({ timeout: 15_000 });

  // GSTR-1 for the month.
  // Cancelling lands back on the invoice; wait for that before leaving, so the move doesn't swallow the next click.
  await expect(page).toHaveURL(/\/documents\/[0-9a-f-]{36}$/);
  await page.goto(`/b/${businessId}/filing`);
  await expect(page.getByRole("heading", { level: 1, name: "Your GST filing" })).toBeVisible();
  await noSeriousAxeFindings(page);
  const month = inv1.slice(4, 9); // YY-MM
  const label = new Date(`20${month.slice(0, 2)}-${month.slice(3)}-01`).toLocaleString("en-IN", { month: "short", year: "numeric" });
  await page.getByRole("link", { name: new RegExp(`^Open GSTR-1 for ${label.replace(/[^A-Za-z0-9 ]/g, ".")}`) }).first().click();
  await expect(page.getByRole("heading", { level: 1, name: /^GSTR-1, / })).toBeVisible();
  await noSeriousAxeFindings(page);

  // Totals: 200 - 100 + 50 = 150.00 taxable; CGST and SGST 18.00 - 9.00 + 4.50 = 13.50 each; nothing differs from HSN.
  await page.getByRole("tab", { name: /Checks and totals/ }).click();
  const totals = page.getByRole("region", { name: "Totals" });
  await expect(totals.getByText("Matches")).toBeVisible();
  await expect(totals.locator(".kv").filter({ hasText: "Taxable value in this return" })).toContainText("150.00");
  await expect(totals.locator(".kv").filter({ hasText: "CGST in this return" })).toContainText("13.50");
  await expect(page.getByText("Something is wrong on our side")).toHaveCount(0);

  await page.getByRole("tab", { name: "What is in the return" }).click();
  await page.getByRole("button", { name: "See the rows of Sales to businesses (B2B)" }).click();
  await expect(page.getByRole("row").filter({ hasText: inv1 })).toContainText(BUYER_GSTIN);
  await expect(page.getByRole("row").filter({ hasText: inv2 })).toHaveCount(0);
  await noSeriousAxeFindings(page);
  await page.getByRole("button", { name: "All sections" }).click();

  await page.getByRole("button", { name: "See the rows of Credit and debit notes to businesses (CDNR)" }).click();
  await expect(page.getByRole("row").filter({ hasText: /^CN\// }).or(page.getByRole("row").filter({ hasText: "CN/" }))).toContainText("Credit (takes off)");
  await expect(page.getByRole("row").filter({ hasText: "DN/" })).toContainText("Debit (adds)");
  await expect(page.getByRole("row").filter({ hasText: "DN/" })).toContainText(inv1);
  await page.getByRole("button", { name: "All sections" }).click();

  // HSN: quantity 2 - 1 = 1 (the debit note moves value only), taxable 150.00.
  await page.getByRole("button", { name: "See the rows of HSN summary: business sales (HSN)" }).click();
  const hsn = page.getByRole("row").filter({ hasText: "340111" });
  await expect(hsn).toContainText("1.000");
  await expect(hsn).toContainText("150.00");
  await page.getByRole("button", { name: "All sections" }).click();

  // Documents issued (Table 13): two invoices, one cancelled; one credit note; one debit note. Confirm them.
  await page.getByRole("tab", { name: /Documents issued/ }).click();
  const invoices = page.getByRole("row").filter({ hasText: "Invoices for outward supply" });
  await expect(invoices).toContainText(inv1);
  await expect(invoices).toContainText(inv2);
  await expect(page.getByRole("row").filter({ hasText: "Debit note" })).toContainText("DN/");
  await expect(page.getByRole("row").filter({ hasText: "Credit note" })).toContainText("CN/");
  await noSeriousAxeFindings(page);
  await page.getByRole("button", { name: /^Confirm/ }).first().click();
  await expect(page.getByRole("tab", { name: /Documents issued/ })).toContainText("Confirmed");

  // GSTR-3B worksheet: 3.1(a) has the same net taxable value and tax.
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Your GST filing" }).click();
  await page.getByRole("link", { name: new RegExp(`^Open the GSTR-3B worksheet for ${label.replace(/[^A-Za-z0-9 ]/g, ".")}`) }).click();
  await expect(page.getByRole("heading", { level: 1, name: /^GSTR-3B worksheet/ })).toBeVisible();
  await page.getByRole("button", { name: "Build the worksheet" }).click();
  const outward = page.getByRole("row", { name: /^\(a\) Outward taxable supplies/ });
  await expect(outward).toContainText("150.00", { timeout: 15_000 });
  await expect(outward).toContainText("13.50");
  await noSeriousAxeFindings(page);
});
