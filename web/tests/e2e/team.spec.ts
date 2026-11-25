import { expect, test } from "@playwright/test";

import { createBusiness, inviteLinkFor, signUp } from "./helpers";

// The invitation link the local demo prints, followed end to end against the real API: no mocked fetch.
// The invited person reads the link from the same mail file the demo's terminal prints it from.
test("an invitation link works for a new person and for someone who already has an account", async ({ page, browser }, info) => {
  const stamp = `${info.project.name}-${Date.now()}`;
  const owner = `e2e-owner-${stamp}@example.com`;
  const existing = `e2e-existing-${stamp}@example.com`;
  const fresh = `e2e-new-${stamp}@example.com`;
  const password = "Seven-Lamps-42!";

  // Someone who already has an account (signed up, then signed out).
  const other = await browser.newContext();
  const o = await other.newPage();
  await signUp(o, existing, password);
  await o.getByRole("button", { name: "Sign out" }).click();
  await expect(o.getByRole("heading", { name: "Sign in" })).toBeVisible();

  await signUp(page, owner, password);
  await createBusiness(page);
  await page.goto(page.url().replace(/\/home$/, "/settings/team"));
  await expect(page.getByRole("heading", { name: "Your team" })).toBeVisible();
  await page.getByRole("tab", { name: "Invite someone" }).click();
  for (const email of [existing, fresh]) {
    await page.getByLabel("Email", { exact: true }).fill(email);
    await page.getByLabel("Role", { exact: true }).selectOption("billing");
    await page.getByRole("button", { name: "Send invitation" }).click();
    await expect(page.getByText(`Invitation sent to ${email}.`)).toBeVisible();
  }
  // The link is never shown on the Team page.
  await expect(page.getByText(/\/invite\//)).toHaveCount(0);

  // Existing account: open the link, sign in with the invited email, accept.
  const linkExisting = await inviteLinkFor(existing);
  expect(linkExisting).toMatch(/\/invite\/.+/);
  await o.goto(new URL(linkExisting).pathname);
  await expect(o.getByRole("heading", { name: "You have been invited" })).toBeVisible();
  await o.getByRole("link", { name: "Sign in" }).click();
  await o.getByLabel("Email").fill(existing);
  await o.getByLabel("Password").fill(password);
  await o.getByRole("button", { name: "Sign in" }).click();
  await o.getByRole("button", { name: "Accept the invitation" }).click();
  await expect(o).toHaveURL(/\/b\/[0-9a-f-]{36}\/home$/);
  await other.close();

  // New person: open the link, create the account with the invited email, open the link again, accept.
  const linkNew = await inviteLinkFor(fresh);
  const second = await browser.newContext();
  const n = await second.newPage();
  await n.goto(new URL(linkNew).pathname);
  await expect(n.getByRole("heading", { name: "You have been invited" })).toBeVisible();
  await n.getByRole("link", { name: "Create an account" }).click();
  await signUp(n, fresh, password);
  await n.goto(new URL(linkNew).pathname);
  await n.getByRole("button", { name: "Accept the invitation" }).click();
  await expect(n).toHaveURL(/\/b\/[0-9a-f-]{36}\/home$/);
  await second.close();
});
