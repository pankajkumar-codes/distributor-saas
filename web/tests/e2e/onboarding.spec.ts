import { expect, test } from "@playwright/test";

import { noSeriousAxeFindings, signUp } from "./helpers";

test("create the business with a GSTIN and land on its Home", async ({ page }, info) => {
  await signUp(page, `e2e-onboard-${info.project.name}-${Date.now()}@example.com`);
  await expect(page.getByRole("option", { name: "Maharashtra (27)" }).first()).toBeAttached();
  await noSeriousAxeFindings(page);

  await page.getByLabel("GSTIN").fill("27AAPFU0939F1ZV");
  await expect(page.getByText(/Format and check digit look right\. State code 27 \(Maharashtra\)/)).toBeVisible();
  await page.getByLabel("Legal name (as on GST certificate)").fill("E2E Traders Private Limited");
  await page.getByRole("group", { name: "Turnover this financial year (declared)" }).getByRole("radio", { name: "Up to the limit for quarterly filing (QRMP)" }).check();
  const lastYear = page.getByRole("group", { name: /^What was your turnover last financial year \(FY \d{4}-\d{2}\)\? \(optional\)$/ });
  await lastYear.getByRole("radio", { name: "Up to the limit for quarterly filing (QRMP)" }).check();
  await page.getByRole("radio", { name: "No", exact: true }).check();
  await page.getByLabel("Address line 1").fill("12 Market Road");
  await page.getByLabel("City or town").fill("Pune");
  await page.getByLabel("PIN code").fill("411001");
  await expect(page.getByLabel("State", { exact: true })).toHaveValue("27");
  await noSeriousAxeFindings(page);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);

  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("heading", { name: "Where you sell and how you file" })).toBeVisible();
  await page.getByRole("checkbox", { name: "Amazon" }).check();
  await page.getByRole("radio", { name: "Quarterly (QRMP)" }).check();
  await noSeriousAxeFindings(page);
  await page.getByRole("button", { name: "Finish and see my filing home" }).click();
  await expect(page.getByRole("heading", { name: /^(Welcome|Good (morning|afternoon|evening))/ })).toBeVisible();
  expect(page.url()).toMatch(/\/b\/[0-9a-f-]{36}\/home$/);
  await expect(page.getByText("E2E Traders Private Limited")).toBeVisible();
  // Whether Home shows a rule 61A warning depends on today's date against the window, so
  // the unit tests cover the warning words. The details and the frequency are both done.
  const setup = page.getByRole("region", { name: "Set up your business" });
  await expect(setup.getByText("3 of 6 done")).toBeVisible();
  await expect(setup.getByText("Coming soon").first()).toBeVisible();
  // Filing home (R1-M2): the server's deadlines, none confirmed yet, so each row says to check the portal.
  await page.getByRole("link", { name: "Your GST filing and deadlines" }).click();
  await expect(page.getByRole("heading", { name: "Your GST filing" })).toBeVisible();
  await expect(page.getByRole("table").getByText("GSTR-1").first()).toBeVisible();
  await expect(page.getByText("Check on the GST portal").first()).toBeVisible();
  await noSeriousAxeFindings(page);
  await page.getByRole("link", { name: "Home" }).first().click();
  await expect(page.getByRole("region", { name: "Set up your business" })).toBeVisible();

  // The customer step opens the (still empty) customers list; add one, find it, go back Home.
  const homeUrl = page.url();
  await setup.getByRole("link", { name: "Add your first customer" }).click();
  await expect(page.getByRole("heading", { name: "Customers" })).toBeVisible();
  await expect(page.getByText("No customers yet. Add your first with New customer.")).toBeVisible();
  await noSeriousAxeFindings(page);
  await page.getByRole("link", { name: "New customer" }).click();
  await page.getByLabel("Name", { exact: true }).fill("Asha Stores");
  await page.getByRole("group", { name: "Billing address" }).getByLabel("State", { exact: true }).selectOption("27");
  await page.getByLabel("Credit days").fill("15");
  await noSeriousAxeFindings(page);
  await page.getByRole("button", { name: "Add customer" }).click();
  await expect(page.getByRole("heading", { name: "Asha Stores" })).toBeVisible();
  await page.getByRole("link", { name: "Customers" }).click();
  const customer = page.getByRole("row").filter({ hasText: "Asha Stores" });
  await expect(customer.getByText("Unregistered")).toBeVisible();
  await expect(customer.getByText("Maharashtra")).toBeVisible();
  const overflowC = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflowC).toBeLessThanOrEqual(0);
  await page.goto(homeUrl);

  // The checklist's product step opens the (still empty) products list.
  await setup.getByRole("link", { name: "Add your first product" }).click();
  await expect(page.getByRole("heading", { name: "Products" })).toBeVisible();
  await expect(page.getByText("No products yet. Add your first with New product.")).toBeVisible();
  await noSeriousAxeFindings(page);

  // Add one, then find it in the list (cards at 360 px, a table at 1280 px).
  await page.getByRole("link", { name: "New product" }).click();
  await page.getByLabel("Product code").fill("SOAP-1");
  await page.getByLabel("Name", { exact: true }).fill("Neem soap");
  await page.getByLabel("HSN (optional)").fill("3401");
  await page.getByLabel("Unit", { exact: true }).selectOption("NOS");
  await page.getByLabel("Sale rate per unit, excluding GST (₹)").fill("1234.5");
  await page.getByRole("radio", { name: "Taxable" }).check();
  await page.getByLabel("GST rate", { exact: true }).selectOption("18");
  await noSeriousAxeFindings(page);
  await page.getByRole("button", { name: "Add product" }).click();
  await expect(page.getByRole("heading", { name: "Neem soap" })).toBeVisible();

  // The owner marks the first rate confirmed in the rate history; the list then has no chip.
  const history = page.getByRole("table").getByRole("row").filter({ hasText: "18%" });
  await expect(history.getByText("Not confirmed")).toBeVisible();
  await history.getByRole("button", { name: "Mark confirmed" }).click();
  await page.getByLabel("Your note (optional)").fill("Checked with our CA");
  await page.getByRole("button", { name: "Mark confirmed" }).last().click();
  await expect(history.getByText("Yes (Checked with our CA)")).toBeVisible();
  await noSeriousAxeFindings(page);
  const overflow3 = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow3).toBeLessThanOrEqual(0);
  await page.getByRole("link", { name: "Products" }).click();
  const row = page.getByRole("row").filter({ hasText: "Neem soap" });
  await expect(row.getByText("₹1,234.50")).toBeVisible();
  await expect(row.getByText("18%")).toBeVisible();
  await expect(row.getByText("Not confirmed")).toHaveCount(0);
  await noSeriousAxeFindings(page);
  const overflow2 = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow2).toBeLessThanOrEqual(0);
  await noSeriousAxeFindings(page);

  // Import a file: one new product, one change to Neem soap, one row with a bad HSN.
  await page.getByRole("link", { name: "Import from a file" }).click();
  const csv = [
    "code,name,hsn,unit,sale_rate,gst_rate,gst_rate_valid_from,barcode,tax_category,has_cess",
    "SOAP-2,Rose soap,3401,NOS,40,18,2025-09-22,,taxable,no",
    "SOAP-1,Neem soap,3401,NOS,1300,18,2025-09-22,,taxable,no",
    "SOAP-3,Bad soap,34X,NOS,10,18,2025-09-22,,taxable,no",
  ].join("\r\n");
  await page.getByLabel("File").setInputFiles({ name: "products.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });
  await page.getByRole("button", { name: "Upload and check" }).click();
  await expect(page.getByText(/products\.csv: 1 new, 1 changed, 0 unchanged, 1 with errors/)).toBeVisible({ timeout: 15000 });
  const changed = page.getByRole("row").filter({ hasText: "SOAP-1" });
  await expect(changed.getByText(/→ 1300/)).toBeVisible();
  await expect(page.getByRole("row").filter({ hasText: "SOAP-3" }).getByText("Has errors")).toBeVisible();
  await noSeriousAxeFindings(page);
  const overflow4 = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow4).toBeLessThanOrEqual(0);
  await page.getByRole("button", { name: "Import 2 products" }).click();
  await expect(page.getByText(/Imported: 2 applied/)).toBeVisible({ timeout: 15000 });
  await page.getByRole("link", { name: "Go to products" }).click();
  await expect(page.getByRole("row").filter({ hasText: "Rose soap" }).getByText("Not confirmed")).toBeVisible();
  await expect(page.getByRole("row").filter({ hasText: "Neem soap" }).getByText("₹1,300.00")).toBeVisible();

  // Settings from Home: change the trade name, then see the frequency chosen at sign-up.
  await page.goto(homeUrl);
  const settings = page.getByRole("navigation", { name: "Settings" });
  await settings.getByRole("link", { name: "Business details" }).click();
  await expect(page.getByLabel("Legal name")).toHaveValue("E2E Traders Private Limited");
  // Last year's band, given at sign-up, is shown here and stays editable.
  await expect(
    page.getByRole("group", { name: /^Turnover last financial year/ }).getByRole("radio", { name: "Up to the limit for quarterly filing (QRMP)" }),
  ).toBeChecked();
  await page.getByLabel("Trade name (optional)").fill("E2E Traders");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText(/Saved\. Invoices already finalized keep/)).toBeVisible();
  await noSeriousAxeFindings(page);
  const overflow5 = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow5).toBeLessThanOrEqual(0);
  await page.getByRole("link", { name: "Filing frequency" }).click();
  await expect(page.getByText(/^Every quarter \(QRMP\), from \d{2}-[A-Z][a-z]{2}-\d{4}\.$/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Save frequency" })).toBeVisible();
  await noSeriousAxeFindings(page);
  const overflow6 = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow6).toBeLessThanOrEqual(0);
});

test("a wrong check character is caught before sending", async ({ page }, info) => {
  await signUp(page, `e2e-onboard-bad-${info.project.name}-${Date.now()}@example.com`);
  await page.getByLabel("GSTIN").fill("27AAPFU0939F1ZA");
  await expect(page.getByText("GSTIN check character doesn't match; please re-check the number.")).toBeVisible();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByLabel("GSTIN")).toBeFocused();
  await expect(page.getByRole("heading", { name: "Your business and GST" })).toBeVisible();
});
