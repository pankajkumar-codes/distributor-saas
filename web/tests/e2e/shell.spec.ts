import { expect, test } from "@playwright/test";

import { createBusiness, noSeriousAxeFindings, signUp } from "./helpers";

// Mocks v16 app shell (#396): sidebar and top search on a laptop, bottom tab bar on a phone.
test("the v16 shell: sidebar and search on a laptop, tab bar on a phone", async ({ page }, info) => {
  await signUp(page, `e2e-shell-${info.project.name}-${Date.now()}@example.com`);
  await createBusiness(page);
  await noSeriousAxeFindings(page);

  if (info.project.name.startsWith("phone")) {
    const tabs = page.getByRole("navigation", { name: "Phone" });
    await expect(tabs).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Main" })).toBeHidden();
    await expect(tabs.getByRole("link", { name: "Home" })).toHaveAttribute("aria-current", "page");
    await tabs.getByRole("link", { name: "More" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Business setup" })).toBeVisible();
    await expect(tabs.getByRole("link", { name: "More" })).toHaveAttribute("aria-current", "page");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(0);
    return;
  }

  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(nav).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Phone" })).toBeHidden();
  await expect(nav.locator("a[aria-current=page]")).toHaveText("Home");

  // Your GST filing: exactly one item is current, even though GSTR-1 and GSTR-3B may point here too.
  await nav.getByRole("link", { name: "Your GST filing" }).click();
  await expect(page).toHaveURL(/\/filing$/);
  await expect(nav.locator("a[aria-current=page]")).toHaveCount(1);
  await expect(nav.locator("a[aria-current=page]")).toHaveText("Your GST filing");

  // A child page marks its parent.
  await nav.getByRole("link", { name: "Settings" }).click();
  await page.getByRole("main").getByRole("link", { name: "Your team" }).click();
  await expect(nav.locator("a[aria-current=page]")).toHaveText("Settings");

  // Search suggests nothing until a letter is typed.
  const search = page.getByRole("combobox", { name: "Search invoices, customers and products" });
  await search.focus();
  await expect(page.getByRole("region", { name: "Customers" })).toHaveCount(0);
  await search.fill("zzzz-none");
  await expect(page.getByText(/Nothing matches/)).toBeVisible();

  // The sidebar itself never scrolls on the smallest laptop.
  await page.setViewportSize({ width: 1366, height: 696 });
  const sideOverflow = await page.locator("aside.side").evaluate((el) => el.scrollHeight - el.clientHeight);
  expect(sideOverflow).toBeLessThanOrEqual(0);
});
