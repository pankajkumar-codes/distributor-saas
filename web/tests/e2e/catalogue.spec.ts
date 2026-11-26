import { expect, test, type Page } from "@playwright/test";

import { createBusiness, fitsOneScreen, signUp } from "./helpers";

// Mocks v16 catalogue screens (#398): the product form saves an MRP, the list shows "—" for a blank one, the lists
// page five at a time, and every catalogue screen fits one laptop screen. Laptop only: phone views may scroll.

const JPEG = Buffer.concat([Buffer.from([0xff, 0xd8, 0xff, 0xe0]), Buffer.from("e2e catalogue photo ".repeat(8))]);

async function addProduct(page: Page, businessId: string, name: string, code: string, mrp: string) {
  await page.goto(`/b/${businessId}/products/new`);
  await page.getByLabel("Name", { exact: true }).fill(name);
  await page.getByLabel("Product code").fill(code);
  await page.getByLabel("Unit", { exact: true }).selectOption("NOS");
  await page.getByLabel("Sale rate per unit, excluding GST (₹)").fill("50");
  if (mrp) await page.getByLabel("MRP, incl. GST (₹, optional)").fill(mrp);
  await page.getByRole("radio", { name: "Exempt" }).check();
  await page.getByRole("button", { name: "Add product" }).click();
  await expect(page.getByText(`Added ${name}.`)).toBeVisible();
}

test("catalogue screens: MRP, pages of five, one screen each", async ({ page }, info) => {
  test.skip(info.project.name.startsWith("phone"), "the one-screen rule is for laptops");
  test.setTimeout(180_000);
  await signUp(page, `e2e-catalogue-${Date.now()}@example.com`);
  await createBusiness(page);
  const businessId = page.url().match(/\/b\/([0-9a-f-]{36})\//)![1];
  const b = `/b/${businessId}`;

  // Six products: one more than a page. The first has an MRP, the rest have none.
  await addProduct(page, businessId, "Product A", "E2E-A", "60.50");
  for (const x of ["B", "C", "D", "E", "F"]) await addProduct(page, businessId, `Product ${x}`, `E2E-${x}`, "");

  await page.goto(`${b}/products`);
  await expect(page.getByRole("row").filter({ hasText: "Product A" }).getByText("₹60.50")).toBeVisible();
  await expect(page.getByRole("row").filter({ hasText: "Product B" }).getByText("—")).toBeVisible();
  await expect(page.getByRole("row")).toHaveCount(6); // the head and five rows
  await fitsOneScreen(page);
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page).toHaveURL(/\?page=2$/);
  await expect(page.getByRole("row")).toHaveCount(2);

  // The product form keeps the MRP, and a blank MRP saves as none.
  await page.goto(`${b}/products`);
  await page.getByRole("link", { name: "Product A" }).click();
  await expect(page.getByLabel("MRP, incl. GST (₹, optional)")).toHaveValue("60.50");
  await fitsOneScreen(page);
  await page.getByLabel("MRP, incl. GST (₹, optional)").fill("");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText("Saved. Invoices already finalized keep the details they were issued with.")).toBeVisible();
  await page.goto(`${b}/products?q=E2E-A`);
  await expect(page.getByRole("row").filter({ hasText: "Product A" }).getByText("—")).toBeVisible();

  await page.goto(`${b}/products/new`);
  await expect(page.getByRole("group", { name: "GST treatment" })).toBeVisible();
  await fitsOneScreen(page);

  // A customer, its page and the list.
  await page.goto(`${b}/customers/new`);
  await fitsOneScreen(page);
  await page.getByLabel("Name", { exact: true }).fill("Asha Stores");
  await page.getByRole("group", { name: "Billing address" }).getByLabel("State", { exact: true }).selectOption("27");
  await page.getByRole("button", { name: "Add customer" }).click();
  await expect(page.getByText("Added Asha Stores.")).toBeVisible();
  await fitsOneScreen(page);
  await page.getByRole("link", { name: "Asha Stores" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Asha Stores" })).toBeVisible();
  await fitsOneScreen(page);

  // Stock, import, purchases and the plan.
  await page.goto(`${b}/stock`);
  await expect(page.getByRole("heading", { level: 1, name: "Stock" })).toBeVisible();
  await expect(page.getByRole("row").filter({ hasText: "Product A" })).toBeVisible();
  await fitsOneScreen(page);

  await page.goto(`${b}/products/import`);
  await expect(page.getByRole("heading", { level: 1, name: "Import products" })).toBeVisible();
  // #425: the template is a plain link to a static file, so the browser itself downloads it.
  const download = page.waitForEvent("download");
  await page.getByRole("link", { name: "Download the template" }).click();
  expect((await download).suggestedFilename()).toBe("products-template.csv");
  await fitsOneScreen(page);

  await page.goto(`${b}/purchases`);
  await expect(page.getByRole("heading", { level: 1, name: "Purchase invoices" })).toBeVisible();
  await page.getByLabel("Choose an invoice (PDF, JPG, PNG or HEIC)").setInputFiles({ name: "catalogue-bill.jpg", mimeType: "image/jpeg", buffer: JPEG });
  const toCheck = page.getByRole("link", { name: /Invoice to type in from catalogue-bill\.jpg/ });
  await expect(toCheck).toBeVisible({ timeout: 20_000 });
  await fitsOneScreen(page);
  await toCheck.click();
  await expect(page.getByRole("heading", { level: 1, name: "Check this invoice" })).toBeVisible();
  await fitsOneScreen(page);

  // #412: a read invoice with every field hard to read still fits. No reader runs locally, so the draft is
  // dressed up in the browser as if one had read it.
  const LINE_FIELDS = ["hsn", "quantity", "unit", "taxable_value", "gst_rate", "igst", "cgst", "sgst", "cess"];
  await page.route(/\/purchase-drafts\/[0-9a-f-]{36}$/, async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    const line = { id: "l-e2e", line_no: 1, page: 1, hsn: "3401", quantity: "1", unit: "NOS", taxable_value: "10.00", gst_rate: "18", igst: null, cgst: "0.90", sgst: "0.90", cess: null, unclear: LINE_FIELDS };
    await route.fulfill({ response: res, json: { ...body, reader: "pdf_text_v1", unclear: ["supplier_gstin", "doc_number", "doc_date", "invoice_total"], lines: [line, { ...line, id: "l-e2e-2", line_no: 2 }] } });
  });
  await page.reload();
  await expect(page.getByLabel("HSN, line 1")).toHaveValue("3401");
  await expect(page.locator("input.unclear")).toHaveCount(4 + LINE_FIELDS.length);
  await expect(page.getByLabel("HSN, line 1")).toHaveAccessibleDescription("Hard to read. Please check.");
  await fitsOneScreen(page);
  await page.unroute(/\/purchase-drafts\/[0-9a-f-]{36}$/);

  await page.goto(`${b}/settings/plan`);
  await expect(page.getByText(/of 10 used/)).toBeVisible();
  await fitsOneScreen(page);
});
