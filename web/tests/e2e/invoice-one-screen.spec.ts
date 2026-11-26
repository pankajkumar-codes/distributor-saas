import { expect, test } from "@playwright/test";

import { LAPTOPS, createBusiness, fitsOneScreen, signUp } from "./helpers";

// Mocks v16 one-screen rule for New invoice with a full invoice (#397, Staff review of #408): six or more lines and a
// "Please check" line, at every laptop size. The page itself never scrolls; only the items box does. Also the live totals
// (#411): the paper's total moves when a quantity changes, before any save, and line discounts (#435). Laptop only: a phone page may scroll.
test("New invoice with many lines and a check still fits one screen; the items box scrolls", async ({ page }, info) => {
  test.skip(info.project.name.startsWith("phone"), "the one-screen rule is for laptops");
  test.setTimeout(120_000);
  let token = "";
  page.on("request", (r) => {
    const auth = r.headers()["authorization"];
    if (auth) token = auth;
  });
  await signUp(page, `e2e-onescreen-${Date.now()}@example.com`);
  await createBusiness(page);
  const businessId = page.url().match(/\/b\/([0-9a-f-]{36})\//)![1];
  await expect.poll(() => token).not.toBe("");

  // Set up through the API: a customer and seven products (the forms for these have their own tests).
  const post = async (path: string, data: object) => {
    const r = await page.request.post(`/api/v1/b/${businessId}/${path}`, {
      data,
      headers: { authorization: token, "Idempotency-Key": crypto.randomUUID() },
    });
    expect(r.status(), await r.text()).toBe(201);
  };
  await post("customers", { name: "Kiran Traders", billing: { line1: "4 Station Road", city: "Pune", pin: "411001", state_code: "27" } });
  // Each MRP is the sale rate with 18% GST, so the rate the MRP implies (D-107) is the sale rate: 47.20 / 1.18 = 40.00.
  const MRPS = ["47.20", "48.38", "49.56", "50.74", "51.92", "53.10", "54.28"];
  const names = ["Neem soap", "Aloe gel", "Rose water", "Tulsi drops", "Amla oil", "Sandal powder", "Mint balm"];
  for (const [i, name] of names.entries())
    await post("products", {
      code: `OS-${i + 1}`, name, hsn: "340111", uqc: "NOS", sale_rate: `${40 + i}.00`, mrp: MRPS[i], tax_category: "taxable",
      rate: { rate: "18", valid_from: "2025-09-22" },
    }); // fmt: skip

  await page.goto(`/b/${businessId}/invoices/new`);
  await page.getByLabel("Find a customer").fill("Kiran");
  await page.getByRole("button", { name: /Kiran Traders/ }).click();
  for (const name of names) {
    await page.getByLabel("Add a product").fill(name);
    await page.getByRole("button", { name: new RegExp(name) }).first().click();
    await expect(page.getByLabel(`Quantity of ${name}`)).toBeVisible();
  }
  const items = page.getByRole("region", { name: "Items" });
  await expect(items.getByRole("row")).toHaveCount(names.length + 1); // with the header row

  // Live totals (#411): the line and the paper show the server's figures for the form as typed, before any save.
  const paper = page.getByRole("region", { name: "Invoice preview" });
  await expect(items.getByRole("row").filter({ hasText: "Neem soap" })).toContainText("₹40.00");
  await page.getByLabel("Quantity of Neem soap").fill("3");
  await expect(items.getByRole("row").filter({ hasText: "Neem soap" })).toContainText("₹120.00");
  await expect(paper.getByText("Total", { exact: true }).locator("..")).not.toContainText("—");

  // Line discounts as a percent or an amount, and one discount for every line (#435).
  await page.getByLabel("Discount on Neem soap: rupees or percent").selectOption("percent");
  await page.getByLabel("Discount on Neem soap in percent").fill("10");
  await expect(items.getByRole("row").filter({ hasText: "Neem soap" })).toContainText("₹108.00");
  const every = page.getByRole("group", { name: "Same discount on every line" });
  await every.getByLabel("Discount for every line in percent").fill("5");
  await every.getByRole("button", { name: "Apply to all lines" }).click();
  await expect(items.getByRole("row").filter({ hasText: "Neem soap" })).toContainText("₹114.00");
  await expect(page.getByLabel("Discount on Mint balm in percent")).toHaveValue("5");

  await page.getByRole("button", { name: /^Save/ }).click();
  await expect(page.getByRole("heading", { name: "Draft invoice" })).toBeVisible();
  // No stock and an unconfirmed GST rate on every line: the notes under each line and the "Please check" line show.
  await expect(page.getByText("Please check:", { exact: true })).toBeVisible();

  await fitsOneScreen(page);
  for (const size of LAPTOPS) {
    await page.setViewportSize(size);
    const box = await page.locator(".itemscroll").evaluate((e) => ({ scroll: e.scrollHeight, client: e.clientHeight }));
    expect(box.scroll, `the items box scrolls at ${size.width}x${size.height}`).toBeGreaterThan(box.client);
  }
});
