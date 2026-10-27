import AxeBuilder from "@axe-core/playwright";
import { expect, type Page } from "@playwright/test";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

// LocalFileMailer's file, relative to where the API was started (the repo root).
const OUTBOX = resolve(process.env.MAIL_OUTBOX ?? "../build/mail/outbox.jsonl");

export async function codeFor(email: string): Promise<string> {
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

export async function noSeriousAxeFindings(page: Page) {
  const { violations } = await new AxeBuilder({ page }).analyze();
  const serious = violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
}

/** Signs a new user up and stops on the onboarding screen. */
export async function signUp(page: Page, email: string, password = "seven lamps under a bridge") {
  await page.goto("/signup");
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Email me a code" }).click();
  await page.getByLabel("Digit 1 of 6").fill(await codeFor(email));
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Your business and GST" })).toBeVisible();
}
