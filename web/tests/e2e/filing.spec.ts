import { expect, test, type Page } from "@playwright/test";

import { createBusiness, fitsOneScreen, noSeriousAxeFindings, signUp } from "./helpers";

/** Clicks every tab on the page in turn and checks each one fits one laptop screen (mocks v16 one-screen rule). */
async function everyTabFits(page: Page) {
  const tabs = page.getByRole("tab");
  const n = await tabs.count();
  expect(n).toBeGreaterThan(1);
  for (let i = 0; i < n; i++) {
    await page.setViewportSize({ width: 1280, height: 800 });
    await tabs.nth(i).click();
    await expect(tabs.nth(i)).toHaveAttribute("aria-selected", "true");
    await fitsOneScreen(page);
  }
  await page.setViewportSize({ width: 1280, height: 800 });
}

// Mocks v16 GST filing screens (#399): Your GST filing, the GSTR-1 return in tabs, the GSTR-3B worksheet in tabs and
// the portal guides, each on one laptop screen. A new business has empty returns, which is the shortest case; the
// longest cases are checked against a fake API while building and by the unit tests.
test("the v16 GST filing screens fit one laptop screen", async ({ page }, info) => {
  test.skip(info.project.name.startsWith("phone"), "phones may scroll (mocks v16 one-screen rule is for laptops)");
  await signUp(page, `e2e-filing-${Date.now()}@example.com`);
  await createBusiness(page);

  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Your GST filing" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Your GST filing" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Deadlines" })).toBeVisible();
  await fitsOneScreen(page);
  await page.setViewportSize({ width: 1280, height: 800 });

  await page.getByRole("link", { name: /^Open GSTR-1 for / }).first().click();
  await expect(page.getByRole("heading", { level: 1, name: /^GSTR-1, / })).toBeVisible();
  await expect(page.getByRole("list", { name: "Steps for this return" })).toBeVisible();
  await noSeriousAxeFindings(page);
  await everyTabFits(page);

  await page.goto(page.url().replace(/\?.*$/, "") + "/portal-guide");
  await expect(page.getByRole("heading", { level: 1, name: "Upload GSTR-1 on the GST portal" })).toBeVisible();
  await everyTabFits(page);

  await page.getByRole("link", { name: "GSTR-3B entry" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Enter GSTR-3B on the GST portal" })).toBeVisible();
  await fitsOneScreen(page);
  await page.setViewportSize({ width: 1280, height: 800 });

  await page.getByRole("link", { name: "Back to the worksheet" }).click();
  await expect(page.getByRole("heading", { level: 1, name: /^GSTR-3B worksheet/ })).toBeVisible();
  await expect(page.getByRole("tab", { name: "3.1 Outward" })).toBeVisible();
  await noSeriousAxeFindings(page);
  await everyTabFits(page);
});

// Part 2 of #399: the upload screen and the two period screens, on one laptop screen and with no serious axe finding.
test("the v16 upload and period screens fit one laptop screen", async ({ page }, info) => {
  test.skip(info.project.name.startsWith("phone"), "phones may scroll (mocks v16 one-screen rule is for laptops)");
  await signUp(page, `e2e-uploads-${Date.now()}@example.com`);
  await createBusiness(page);
  const nav = page.getByRole("navigation", { name: "Main" });

  await nav.getByRole("link", { name: "Upload your reports" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Upload your reports" })).toBeVisible();
  await expect(page.getByRole("region", { name: "A zip of your reports" })).toBeVisible();
  await noSeriousAxeFindings(page);
  await fitsOneScreen(page);
  await page.setViewportSize({ width: 1280, height: 800 });

  await nav.getByRole("link", { name: "File from own invoices" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "File from your own invoices" })).toBeVisible();
  await page.getByLabel("Month").selectOption({ index: 1 });
  await expect(page.getByRole("button", { name: "Get my GSTR-1 file" })).toBeVisible();
  await noSeriousAxeFindings(page);
  await fitsOneScreen(page);
  await page.setViewportSize({ width: 1280, height: 800 });

  await nav.getByRole("link", { name: /^Monthly\/quarterly files$/ }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Monthly and quarterly files" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Files made before" })).toBeVisible();
  await noSeriousAxeFindings(page);
  await fitsOneScreen(page);
});
