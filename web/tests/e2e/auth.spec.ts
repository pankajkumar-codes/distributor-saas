import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

// LocalFileMailer's file, relative to where the API was started (the repo root).
const OUTBOX = resolve(process.env.MAIL_OUTBOX ?? "../build/mail/outbox.jsonl");

async function codeFor(email: string): Promise<string> {
  let code: string | undefined;
  await expect
    .poll(() => {
      const lines = existsSync(OUTBOX) ? readFileSync(OUTBOX, "utf8").trim().split("\n") : [];
      const mine = lines.map((l) => JSON.parse(l)).filter((m) => m.to === email && m.template === "signup_code");
      code = mine.at(-1)?.params.code;
      return code;
    })
    .toBeTruthy();
  return code!;
}

async function noSeriousAxeFindings(page: Page) {
  const { violations } = await new AxeBuilder({ page }).analyze();
  const serious = violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
}

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
  await page.goto("/signup");
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Email me a code" }).click();
  await page.getByLabel("Digit 1 of 6").fill(await codeFor(email));
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Your business and GST" })).toBeVisible();

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
