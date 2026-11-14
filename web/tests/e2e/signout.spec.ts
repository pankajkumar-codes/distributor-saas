import { expect, test } from "@playwright/test";

import { createBusiness, signUp } from "./helpers";

// The real button against the real API: no mocked fetch, no mocked session.
test("Sign out ends the session: protected pages go to sign-in, and a reload stays signed out", async ({ page }, info) => {
  await signUp(page, `e2e-signout-${info.project.name}-${Date.now()}@example.com`);
  await createBusiness(page);
  const signoutCalls: number[] = [];
  page.on("response", (r) => {
    if (r.url().endsWith("/api/v1/auth/signout")) signoutCalls.push(r.status());
  });
  const homeUrl = page.url();

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/signin$/); // no ?next=: the page they left is not remembered
  await expect(page.getByRole("heading", { name: /sign in/i })).toBeVisible();
  expect(signoutCalls).toEqual([204]);

  // The server forgot the session: the refresh cookie no longer works.
  const refreshed = await page.request.post("/api/v1/auth/refresh", { headers: { Origin: "http://localhost:5173" } });
  expect(refreshed.status()).toBe(401);

  // Protected pages send a signed-out visitor to sign-in, also after a reload and on Back.
  await page.goto(homeUrl);
  await expect(page).toHaveURL(/\/signin/);
  await page.reload();
  await expect(page).toHaveURL(/\/signin/);
  await page.goBack();
  await expect(page).toHaveURL(/\/signin/);
  await expect(page.getByRole("button", { name: "Sign out" })).toHaveCount(0);
});

// Chrome user report: "nothing happened on clicking". Whatever the server does with the
// request, the button signs this tab out and goes to sign-in.
for (const [name, fulfil] of [
  ["a 401 (Origin or session refused)", (route: import("@playwright/test").Route) => route.fulfill({ status: 401, contentType: "application/json", body: '{"error":{"code":"session_invalid"}}' })],
  ["a 500", (route: import("@playwright/test").Route) => route.fulfill({ status: 500 })],
  ["a dropped connection", (route: import("@playwright/test").Route) => route.abort("failed")],
] as const) {
  test(`Sign out still signs this tab out when the server answers with ${name}`, async ({ page }, info) => {
    await signUp(page, `e2e-signout-fail-${info.project.name}-${Date.now()}@example.com`);
    await createBusiness(page);
    await page.route("**/api/v1/auth/signout", fulfil);
    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/signin$/);
    await expect(page.getByRole("heading", { name: /sign in/i })).toBeVisible();
    await expect(page.getByRole("button", { name: "Sign out" })).toHaveCount(0);
  });
}
