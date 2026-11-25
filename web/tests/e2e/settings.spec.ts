import { expect, test } from "@playwright/test";

import { fitsOneScreen, signUp } from "./helpers";

// Mocks v16 one-screen rule for #400: Business setup and each Settings sub-page fit a laptop
// screen without page scrolling. Phone views are exempt.
test("Business setup and its sub-pages fit one laptop screen", async ({ page }, info) => {
  test.skip(info.project.name.startsWith("phone"), "the one-screen rule is for laptops");
  await signUp(page, `e2e-settings-${Date.now()}@example.com`);
  // Onboarding (#404): the business step and the how-you-sell step each fit too.
  await page.getByLabel("GSTIN").fill("27AAPFU0939F1ZV");
  await page.getByLabel("Legal name (as on GST certificate)").fill("E2E Traders Private Limited");
  await page.getByLabel("Address line 1").fill("12 Market Road");
  await page.getByLabel("City or town").fill("Pune");
  await page.getByLabel("PIN code").fill("411001");
  await test.step("Onboarding: your business and GST", () => fitsOneScreen(page));
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("group", { name: "Turnover this financial year (declared)" }).getByRole("radio", { name: "Up to the limit for quarterly filing (QRMP)" }).check();
  await page.getByRole("radio", { name: "No", exact: true }).check();
  await page.getByRole("checkbox", { name: "Amazon" }).check();
  await page.getByRole("radio", { name: "Quarterly (QRMP)" }).check();
  await test.step("Onboarding: how you sell and file", () => fitsOneScreen(page));
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.getByRole("button", { name: "Finish and see my filing home" }).click();
  await expect(page).toHaveURL(/\/b\/[0-9a-f-]{36}\/home$/);
  const main = page.getByRole("main");

  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Settings" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Business setup" })).toBeVisible();
  await expect(main.getByText("E2E Traders Private Limited")).toBeVisible();
  await fitsOneScreen(page);

  // Change opens each part's form on the same page; each tab of it fits too (#404).
  await page.getByRole("link", { name: "Change business details" }).click();
  for (const name of ["Name and address", "Turnover and e-invoicing"]) {
    await page.getByRole("tab", { name }).click();
    await test.step(`Business details: ${name}`, () => fitsOneScreen(page));
  }
  await page.getByRole("link", { name: "Back to Business setup" }).click();
  await page.getByRole("link", { name: "Change filing frequency" }).click();
  await expect(page.getByRole("radio", { name: "Every quarter (QRMP)" })).toBeChecked();
  await test.step("Filing frequency", () => fitsOneScreen(page));
  await page.getByRole("link", { name: "Back to Business setup" }).click();

  await main.getByRole("link", { name: "Your team" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Your team" })).toBeVisible();
  for (const name of [/^Members/, /^Invite someone/, /^Invitations/]) {
    await page.getByRole("tab", { name }).click();
    await expect(page.getByRole("tab", { name })).toHaveAttribute("aria-selected", "true");
    await fitsOneScreen(page);
  }

  for (const [link, heading] of [
    ["Audit log", "Audit log"],
    ["Two-step sign-in", "Two-step sign-in"],
    ["Support access", "Support access"],
  ] as const) {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Settings" }).click();
    await main.getByRole("link", { name: link }).click();
    await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
    await expect(page.getByText("Loading…")).toHaveCount(0);
    await test.step(heading, () => fitsOneScreen(page));
  }
});
