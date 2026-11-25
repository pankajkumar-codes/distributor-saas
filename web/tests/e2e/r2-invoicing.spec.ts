import { expect, test, type Page } from "@playwright/test";

import { fitsOneScreen, noSeriousAxeFindings, signUp } from "./helpers";

// The R2 happy path in a real browser (R2-M8): business type, a purchase invoice kept as a photo and typed in, confirm
// into products and stock, the selling price, a practice sales invoice that takes the stock out, and its PDF request.
// Needs `sales.finalize.enabled` on (tests/e2e/enable-finalize.sql). Not covered here: the 11th-invoice block (it needs
// FREE_FOR_NOW off, a code constant; the backend tests cover it) and the PDF file itself (the renderer Lambda does not run
// locally; CI's `renderer` job tests the template).

// A tiny JPEG: the server checks the file's first bytes, and no reader for pictures is switched on, so it gets a blank draft.
const JPEG = Buffer.concat([Buffer.from([0xff, 0xd8, 0xff, 0xe0]), Buffer.from("e2e purchase photo ".repeat(8))]);

async function createDistributor(page: Page) {
  await page.getByLabel("GSTIN").fill("27AAPFU0939F1ZV");
  await page.getByLabel("Legal name (as on GST certificate)").fill("E2E Distributors Private Limited");
  await page.getByLabel("Address line 1").fill("12 Market Road");
  await page.getByLabel("City or town").fill("Pune");
  await page.getByLabel("PIN code").fill("411001");
  await page.getByRole("checkbox", { name: "Distributor" }).check();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("group", { name: "Turnover this financial year (declared)" }).getByRole("radio", { name: "Up to the limit for quarterly filing (QRMP)" }).check();
  await page.getByRole("radio", { name: "No", exact: true }).check();
  await page.getByRole("checkbox", { name: "Amazon" }).check();
  await page.getByRole("radio", { name: "Quarterly (QRMP)" }).check();
  await page.getByRole("button", { name: "Finish and see my filing home" }).click();
  await expect(page).toHaveURL(/\/b\/[0-9a-f-]{36}\/home$/);
}

test("R2: purchase, stock, price, practice invoice, PDF request", async ({ page }, info) => {
  test.setTimeout(120_000);
  await signUp(page, `e2e-r2-${info.project.name}-${Date.now()}@example.com`);
  await createDistributor(page);
  const businessId = page.url().match(/\/b\/([0-9a-f-]{36})\//)![1];

  // A customer to sell to.
  await page.goto(`/b/${businessId}/customers/new`);
  await page.getByLabel("Name", { exact: true }).fill("Asha Stores");
  await page.getByRole("group", { name: "Billing address" }).getByLabel("State", { exact: true }).selectOption("27");
  await page.getByRole("button", { name: "Add customer" }).click();
  await expect(page.getByText("Added Asha Stores.")).toBeVisible(); // adding lands on the Customers list

  // Upload a photo of a supplier invoice: it is kept and the business types it in.
  await page.goto(`/b/${businessId}/purchases`);
  await expect(page.getByRole("heading", { name: "Purchase invoices" })).toBeVisible();
  await page.getByLabel("Choose an invoice (PDF, JPG, PNG or HEIC)").setInputFiles({ name: "supplier-bill.jpg", mimeType: "image/jpeg", buffer: JPEG });
  const toCheck = page.getByRole("link", { name: /Invoice to type in from supplier-bill\.jpg/ });
  await expect(toCheck).toBeVisible({ timeout: 20_000 });
  await noSeriousAxeFindings(page);
  await toCheck.click();
  await expect(page.getByRole("heading", { name: "Check this invoice" })).toBeVisible();

  await page.getByLabel("Supplier GSTIN").fill("29AABCT1332L1ZA");
  await page.getByLabel("Supplier name (optional)").fill("Bright Wholesale");
  await page.getByLabel("Invoice number").fill("BW-1001");
  await page.getByLabel("Invoice date").fill("2026-11-10");
  // The blank draft already has one empty line to fill in.
  await page.getByLabel("Product name, line 1").fill("Neem soap");
  await page.getByLabel("HSN, line 1").fill("340111");
  await page.getByLabel("Quantity, line 1").fill("10");
  await page.getByLabel("Unit, line 1").fill("NOS");
  await page.getByLabel("Taxable value, line 1").fill("500");
  await page.getByLabel("GST rate %, line 1").fill("18");
  await page.getByLabel("IGST, line 1").fill("90");
  await page.getByLabel("Product code, line 1").fill("SOAP-E2E");
  await page.getByLabel("Unit code (UQC), line 1").fill("NOS");
  await page.getByLabel("Tax category, line 1").selectOption("taxable");
  await page.getByLabel("GST rate applies from, line 1").fill("2025-09-22");
  await noSeriousAxeFindings(page);
  await page.getByRole("button", { name: "Confirm and add to my products" }).click();

  // The stock is there and the product still needs a selling price per 1 qty.
  await page.goto(`/b/${businessId}/stock`);
  const stockRow = page.getByRole("row").filter({ hasText: "Neem soap" });
  await expect(stockRow).toBeVisible({ timeout: 15_000 });
  await expect(stockRow.getByText("10.000 NOS")).toBeVisible();
  await page.getByLabel("Price per 1 NOS (excl. GST) for Neem soap").fill("80");
  await page.getByRole("button", { name: "Save price" }).click();
  await expect(stockRow.getByText("₹80.00")).toBeVisible();

  // A practice invoice from the catalogue.
  await page.goto(`/b/${businessId}/invoices/new`);
  await page.getByLabel("Find a customer").fill("Asha");
  await page.getByRole("button", { name: "Asha Stores" }).click();
  await page.getByLabel("Add a product").fill("Neem");
  await page.getByRole("button", { name: /Neem soap/ }).first().click();
  await page.getByLabel("Quantity").fill("3");
  await page.getByRole("button", { name: /^Save/ }).click();
  await expect(page.getByRole("heading", { name: "Draft invoice" })).toBeVisible();
  await page.getByRole("button", { name: /^Create (practice )?invoice/ }).click();
  await expect(page.getByRole("heading", { name: "Invoice issued" })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("Practice invoice.")).toBeVisible();
  await expect(page.getByText("It is not a tax invoice and is not in any GST return.")).toBeVisible();
  // The issued page shows the buyer, the line with its tax split and the totals, and fits the screen.
  await expect(page.getByText("Practice · not for customers")).toBeVisible();
  await expect(page.getByText("Asha Stores").first()).toBeVisible();
  const line = page.getByRole("row").filter({ hasText: "Neem soap" });
  await expect(line).toContainText("HSN 340111");
  await expect(line).toContainText("3 NOS");
  await expect(line).toContainText("CGST");
  await expect(line).toContainText("SGST");
  await expect(page.getByRole("heading", { name: "Totals" })).toBeVisible();
  await expect(page.getByText("Taxable value", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await noSeriousAxeFindings(page);

  // The PDF is asked for in the background; the button survives a reload.
  const asked = page.waitForResponse((r) => /\/documents\/[0-9a-f-]{36}\/pdf$/.test(r.url()) && r.request().method() === "POST");
  await page.getByRole("button", { name: "Download practice PDF" }).click();
  expect((await asked).status()).toBe(202);
  await expect(page.getByRole("button", { name: "Download practice PDF" })).toBeVisible();

  // The invoice is read from the server: from the list, on another visit, it is still there with its PDF button.
  await page.goto(`/b/${businessId}/documents`);
  await expect(page.getByRole("heading", { name: "Issued invoices" })).toBeVisible();
  const issued = page.getByRole("row").filter({ hasText: "Asha Stores" });
  await expect(issued.getByText("Practice", { exact: true })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Pages of invoices" })).toBeVisible();
  if (!info.project.name.startsWith("phone")) {
    // Mocks v16 one-screen rule: the lists page instead of scrolling, and Home with its tabs fits too.
    await fitsOneScreen(page);
    await page.goto(`/b/${businessId}/drafts`);
    await expect(page.getByRole("heading", { name: "Draft invoices" })).toBeVisible();
    await fitsOneScreen(page);
    await page.goto(`/b/${businessId}/home`);
    await page.getByRole("tab", { name: "Recent invoices" }).click();
    await expect(page.getByRole("row").filter({ hasText: "Asha Stores" })).toBeVisible();
    await fitsOneScreen(page);
    // The top bar finds the invoice by its buyer.
    await page.getByRole("combobox", { name: "Search invoices, customers and products" }).fill("Asha");
    await expect(page.getByRole("region", { name: "Invoices" }).getByRole("link", { name: /Asha Stores/ })).toBeVisible();
    await page.goto(`/b/${businessId}/documents`);
  }
  await issued.getByRole("link").click();
  await expect(page.getByRole("button", { name: "Download practice PDF" })).toBeVisible();

  // Stock went down by what was sold, and the plan page counts the invoice against the free ones.
  await page.goto(`/b/${businessId}/stock`);
  await expect(page.getByRole("row").filter({ hasText: "Neem soap" }).getByText("7.000 NOS")).toBeVisible();
  await page.goto(`/b/${businessId}/settings/plan`);
  await expect(page.getByText("Free for now.")).toBeVisible();
  await expect(page.getByText(/1 of 10/)).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  await noSeriousAxeFindings(page);
});
