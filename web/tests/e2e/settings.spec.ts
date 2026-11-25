import { expect, test } from "@playwright/test";

import { createBusiness, fitsOneScreen, signUp } from "./helpers";

// Mocks v16 one-screen rule for #400: Business setup and each Settings sub-page fit a laptop
// screen without page scrolling. Phone views are exempt.
test("Business setup and its sub-pages fit one laptop screen", async ({ page }, info) => {
  test.skip(info.project.name.startsWith("phone"), "the one-screen rule is for laptops");
  await signUp(page, `e2e-settings-${Date.now()}@example.com`);
  await createBusiness(page);
  const main = page.getByRole("main");

  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Settings" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Business setup" })).toBeVisible();
  await expect(main.getByText("E2E Traders Private Limited")).toBeVisible();
  await fitsOneScreen(page);

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
