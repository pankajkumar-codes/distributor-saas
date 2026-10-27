import { expect, test } from "@playwright/test";

import { noSeriousAxeFindings, signUp } from "./helpers";

test("create the business with a GSTIN and land on its Home", async ({ page }, info) => {
  await signUp(page, `e2e-onboard-${info.project.name}-${Date.now()}@example.com`);
  await expect(page.getByRole("option", { name: "Maharashtra (27)" }).first()).toBeAttached();
  await noSeriousAxeFindings(page);

  await page.getByLabel("GSTIN").fill("27AAPFU0939F1ZV");
  await expect(page.getByText(/Format and check digit look right\. State code 27 \(Maharashtra\)/)).toBeVisible();
  await page.getByLabel("Legal name (as on GST certificate)").fill("E2E Traders Private Limited");
  await page.getByRole("radio", { name: "Up to the limit for quarterly filing (QRMP)" }).check();
  await page.getByRole("radio", { name: "No", exact: true }).check();
  await page.getByLabel("Address line 1").fill("12 Market Road");
  await page.getByLabel("City or town").fill("Pune");
  await page.getByLabel("PIN code").fill("411001");
  await expect(page.getByLabel("State", { exact: true })).toHaveValue("27");
  await page.getByRole("radio", { name: "Every quarter (QRMP)" }).check();
  await noSeriousAxeFindings(page);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);

  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("heading", { name: /^(Welcome|Good (morning|afternoon|evening))/ })).toBeVisible();
  expect(page.url()).toMatch(/\/b\/[0-9a-f-]{36}\/home$/);
  await expect(page.getByText("E2E Traders Private Limited")).toBeVisible();
  // Whether Home shows a rule 61A warning depends on today's date against the window, so
  // the unit tests cover the warning words. The details and the frequency are both done.
  const setup = page.getByRole("region", { name: "Set up your business" });
  await expect(setup.getByText("2 of 6 done")).toBeVisible();
  await expect(setup.getByText("Coming soon").first()).toBeVisible();
  await noSeriousAxeFindings(page);
});

test("a wrong check character is caught before sending", async ({ page }, info) => {
  await signUp(page, `e2e-onboard-bad-${info.project.name}-${Date.now()}@example.com`);
  await page.getByLabel("GSTIN").fill("27AAPFU0939F1ZA");
  await expect(page.getByText("GSTIN check character doesn't match; please re-check the number.")).toBeVisible();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByLabel("GSTIN")).toBeFocused();
  await expect(page.getByRole("heading", { name: "Your business and GST" })).toBeVisible();
});
