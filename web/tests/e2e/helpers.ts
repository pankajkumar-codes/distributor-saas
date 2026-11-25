import AxeBuilder from "@axe-core/playwright";
import { expect, type Page } from "@playwright/test";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

// LocalFileMailer's file, relative to where the API was started (the repo root).
const OUTBOX = resolve(process.env.MAIL_OUTBOX ?? "../build/mail/outbox.jsonl");

export async function codeFor(email: string, template = "signup_code"): Promise<string> {
  let code: string | undefined;
  await expect
    .poll(() => {
      const lines = existsSync(OUTBOX) ? readFileSync(OUTBOX, "utf8").trim().split("\n") : [];
      const mine = lines.map((l) => JSON.parse(l)).filter((m) => m.to === email && m.template === template);
      code = mine.at(-1)?.params.code;
      return code;
    })
    .toBeTruthy();
  return code!;
}

/** The accept link in the newest invitation email to this address (the local demo prints the same link). */
export async function inviteLinkFor(email: string): Promise<string> {
  let link: string | undefined;
  await expect
    .poll(() => {
      const lines = existsSync(OUTBOX) ? readFileSync(OUTBOX, "utf8").trim().split("\n") : [];
      const mine = lines.map((l) => JSON.parse(l)).filter((m) => m.to === email && m.template === "invitation");
      link = mine.at(-1)?.params.link;
      return link;
    })
    .toBeTruthy();
  return link!;
}

export async function noSeriousAxeFindings(page: Page) {
  const { violations } = await new AxeBuilder({ page }).analyze();
  const serious = violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
}

/** Signs a new user up and stops on the onboarding screen. */
export async function signUp(page: Page, email: string, password = "Seven-Lamps-42!") {
  await page.goto("/signup");
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Email me a code" }).click();
  await page.getByLabel("Digit 1 of 6").fill(await codeFor(email));
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Your business and GST" })).toBeVisible();
}

/** Fills both onboarding steps with a Maharashtra GSTIN and lands on the new business's Home. */
export async function createBusiness(page: Page, legalName = "E2E Traders Private Limited") {
  await page.getByLabel("GSTIN").fill("27AAPFU0939F1ZV");
  await page.getByLabel("Legal name (as on GST certificate)").fill(legalName);
  await page.getByRole("group", { name: "Turnover this financial year (declared)" }).getByRole("radio", { name: "Up to the limit for quarterly filing (QRMP)" }).check();
  await page.getByRole("radio", { name: "No", exact: true }).check();
  await page.getByLabel("Address line 1").fill("12 Market Road");
  await page.getByLabel("City or town").fill("Pune");
  await page.getByLabel("PIN code").fill("411001");
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("checkbox", { name: "Amazon" }).check();
  await page.getByRole("radio", { name: "Quarterly (QRMP)" }).check();
  await page.getByRole("button", { name: "Finish and see my filing home" }).click();
  await expect(page).toHaveURL(/\/b\/[0-9a-f-]{36}\/home$/);
}

/**
 * Clicks Sign in on a filled form and, if the account is already signed in elsewhere (one active session per user),
 * answers yes, as a person continuing here would.
 */
export async function signInContinuingHere(page: Page) {
  await page.getByRole("button", { name: "Sign in" }).click();
  const yes = page.getByRole("button", { name: /^Yes, sign out there/ });
  await expect(yes.or(page.getByRole("button", { name: "Sign out" })).first()).toBeVisible();
  if (await yes.isVisible()) await yes.click();
}

/**
 * Mocks v16 one-screen rule (BRD UI rules): on a laptop a signed-in screen needs no page
 * scrolling. Phone views and the public landing page are exempt. Use it at 1366x696,
 * 1280x720 and 1536x864, as `docs/mocks/mocks-v16-one-screen-check.js` does for the mocks.
 */
export const LAPTOPS = [
  { width: 1366, height: 696 },
  { width: 1280, height: 720 },
  { width: 1536, height: 864 },
] as const;

export async function fitsOneScreen(page: Page) {
  for (const size of LAPTOPS) {
    await page.setViewportSize(size);
    const extra = await page.evaluate(() => document.documentElement.scrollHeight - window.innerHeight);
    expect(extra, `page scrolls by ${extra}px at ${size.width}x${size.height}`).toBeLessThanOrEqual(0);
  }
}
