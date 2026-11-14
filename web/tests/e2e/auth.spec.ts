import { expect, test } from "@playwright/test";

import { codeFor, noSeriousAxeFindings, signUp } from "./helpers";

test("sign up with an emailed code and land on onboarding", async ({ page }, info) => {
  const email = `e2e-${info.project.name}-${Date.now()}@example.com`;
  const urls: string[] = [];
  page.on("framenavigated", (frame) => urls.push(frame.url()));

  await page.goto("/signup");
  await expect(page.getByRole("heading", { name: "Create your account" })).toBeVisible();
  await noSeriousAxeFindings(page);

  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Password").fill("seven lamps under a bridge");
  await page.getByRole("button", { name: "Email me a code" }).click();
  await expect(page.getByRole("heading", { name: "Check your email" })).toBeVisible();
  await noSeriousAxeFindings(page);

  await page.getByLabel("Digit 1 of 6").fill(await codeFor(email));
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Your business and GST" })).toBeVisible();
  await noSeriousAxeFindings(page);

  // RM-4.1 row 13: the email never reached a URL, and nothing was put in storage.
  expect(urls.length).toBeGreaterThan(0);
  for (const url of urls) expect(url).not.toContain(email.split("@")[0]);
  const stored = await page.evaluate(() => localStorage.length + sessionStorage.length);
  expect(stored).toBe(0);
  // The page fits a 360 px phone with no sideways scroll.
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});

test("a reload on the code step asks for the password again", async ({ page }, info) => {
  const email = `e2e-reload-${info.project.name}-${Date.now()}@example.com`;
  await page.goto("/signup");
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Password").fill("seven lamps under a bridge");
  await page.getByRole("button", { name: "Email me a code" }).click();
  await expect(page.getByRole("heading", { name: "Check your email" })).toBeVisible();

  await page.reload();
  await expect(page.getByText("Enter your password again")).toBeVisible();
  await expect(page.getByText(email)).toBeVisible();
  await page.getByLabel("Password").fill("seven lamps under a bridge");
  await page.getByLabel("Digit 1 of 6").fill(await codeFor(email));
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Your business and GST" })).toBeVisible();
});

test("a reload keeps the session; sign out, then sign in with the password", async ({ page }, info) => {
  const email = `e2e-session-${info.project.name}-${Date.now()}@example.com`;
  const password = "seven lamps under a bridge";
  await signUp(page, email, password);

  await page.reload(); // the token was only in memory: /auth/refresh brings it back
  await expect(page.getByRole("heading", { name: "Your business and GST" })).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await noSeriousAxeFindings(page);
  await page.goto("/onboarding/business"); // signed out for real: the cookie no longer works
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();

  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Your business and GST" })).toBeVisible();
  expect(page.url()).toBe("http://localhost:5173/onboarding/business");
});

test("forgot password: reset with an emailed code, then sign in with the new password", async ({ page }, info) => {
  const email = `e2e-reset-${info.project.name}-${Date.now()}@example.com`;
  await signUp(page, email, "seven lamps under a bridge");
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();

  await page.getByLabel("Email").fill(email);
  await page.getByRole("link", { name: "Forgot your password?" }).click();
  await expect(page.getByRole("heading", { name: "Reset your password" })).toBeVisible();
  await expect(page.getByLabel("Email")).toHaveValue(email);
  await noSeriousAxeFindings(page);
  await page.getByRole("button", { name: "Send code" }).click();
  await expect(page.getByRole("heading", { name: "Check your email" })).toBeVisible();
  expect(page.url()).toBe("http://localhost:5173/reset"); // the email stays out of the URL
  await page.getByLabel("Digit 1 of 6").fill(await codeFor(email, "reset_code"));
  await page.getByLabel("New password").fill("nine kites over a harbour");
  await noSeriousAxeFindings(page);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  await page.getByRole("button", { name: "Set new password" }).click();
  await expect(page.getByText(/Your password is changed, and you're signed out everywhere/)).toBeVisible();

  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("seven lamps under a bridge");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert").or(page.locator(".banner")).first()).toBeVisible(); // the old password no longer works
  await page.getByLabel("Password").fill("nine kites over a harbour");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Your business and GST" })).toBeVisible();
});

// Pankaj's demo: pressing "Email me a code" greyed the button and nothing else happened. A request with no
// answer is given up after 20 s, the screen says so, and the button works again (the real API answers the retry).
test("a code request that gets no answer shows an error and the button works again", async ({ page }, info) => {
  test.setTimeout(60_000);
  const email = `e2e-hang-${info.project.name}-${Date.now()}@example.com`;
  let hang = true;
  await page.route("**/api/v1/auth/signup", async (route) => {
    if (hang) return; // never answered
    await route.continue();
  });
  await page.goto("/signup");
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Password").fill("seven lamps under a bridge");
  const button = page.getByRole("button", { name: "Email me a code" });
  await button.click();
  await expect(button).toBeDisabled();
  await expect(page.getByText("We couldn't reach the server. Check your connection and try again.")).toBeVisible({ timeout: 30_000 });
  await expect(button).toBeEnabled();

  hang = false;
  await button.click();
  await expect(page.getByRole("heading", { name: "Check your email" })).toBeVisible();
  await page.getByLabel("Digit 1 of 6").fill(await codeFor(email));
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Your business and GST" })).toBeVisible();
});

test("a code request the server fails shows an error and the button works again", async ({ page }, info) => {
  const email = `e2e-fail-${info.project.name}-${Date.now()}@example.com`;
  await page.route("**/api/v1/auth/signup", (route) => route.fulfill({ status: 503, body: "" }));
  await page.goto("/signup");
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Password").fill("seven lamps under a bridge");
  const button = page.getByRole("button", { name: "Email me a code" });
  await button.click();
  await expect(page.getByText("Something went wrong on our side. Nothing was lost; try again.")).toBeVisible();
  await expect(button).toBeEnabled();
});
