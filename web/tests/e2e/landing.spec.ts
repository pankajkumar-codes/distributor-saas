import { expect, test } from "@playwright/test";

import { signUp } from "./helpers";

// http://localhost:5173/ is the Kartaa landing page for a visitor with no session; its buttons lead into the app.
test("/ shows the landing page; Sign in and Sign up lead to /signin and /signup", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/localhost:5173\/$/);
  await expect(page.getByRole("heading", { level: 1, name: /Make your invoices once/ })).toBeVisible();

  await page.getByRole("link", { name: "Sign in" }).first().click();
  await expect(page).toHaveURL(/\/signin$/);
  await expect(page.getByRole("heading", { name: /sign in/i })).toBeVisible();

  await page.goto("/");
  await page.getByRole("link", { name: "Sign up" }).first().click();
  await expect(page).toHaveURL(/\/signup$/);
});

test("a signed-in person at / goes to the app, and the landing page is back after sign-out", async ({ page }, info) => {
  await signUp(page, `e2e-landing-${info.project.name}-${Date.now()}@example.com`);
  await page.goto("/");
  await expect(page).toHaveURL(/\/(onboarding\/business|b\/[^/]+\/home|businesses)$/);
  await expect(page.getByRole("heading", { level: 1, name: /Make your invoices once/ })).toHaveCount(0);

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/signin$/);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: /Make your invoices once/ })).toBeVisible();
});
