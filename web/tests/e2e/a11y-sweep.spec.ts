import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { createBusiness, signUp } from "./helpers";

// Accessibility sweep: every signed-in screen of the app, with real data in it (customers, products, an issued invoice,
// a credit note and a debit note by amount, a draft and the returns they fill), checked with axe at both sizes. A
// serious or critical finding fails the test; moderate and minor ones are printed for the report. Practice documents are
// enough here: the live flow is gst-live-documents.spec.ts.

async function bearer(page: Page): Promise<string> {
  const req = page.waitForRequest((r) => r.url().includes("/api/v1/") && !!r.headers()["authorization"]);
  await page.reload();
  return (await req).headers()["authorization"];
}

type Seeded = { customer: string; product: string; invoice: string; note: string; draft: string; gstr1: string; gstr3b: string };

async function seed(page: Page, businessId: string): Promise<Seeded> {
  const auth = await bearer(page);
  const call = async (method: "post" | "get", path: string, data?: object, extra: Record<string, string> = {}) => {
    const r = await page.request[method](`/api/v1/b/${businessId}${path}`, { data, headers: { authorization: auth, "Idempotency-Key": crypto.randomUUID(), ...extra } });
    expect(r.ok(), `${method} ${path}: ${await r.text()}`).toBe(true);
    return r.json();
  };
  const customer = (await call("post", "/customers", { name: "Asha Stores", gstin: "27AABCR5678L1ZR", billing: { line1: "5 MG Road", city: "Pune", pin: "411001", state_code: "27" }, delivery_same_as_billing: true })).id;
  const product = (await call("post", "/products", { code: "SOAP18", name: "Neem soap", hsn: "340111", uqc: "NOS", sale_rate: "100.00", mrp: "118.00", tax_category: "taxable", rate: { rate: "18", valid_from: "2025-09-22" } })).id;
  const lines = [{ product_id: product, quantity: "3" }];
  const d = await call("post", "/drafts", { kind: "invoice", customer_id: customer, lines });
  const invoice = (await call("post", `/drafts/${d.id}/finalize`, undefined, { "If-Match": String(d.version) })).id;
  const credit = await call("get", `/documents/${invoice}/credit`);
  const line = credit.lines[0].original_line_id;
  const note = (await call("post", `/documents/${invoice}/debit-notes`, { reason: "value_too_low", lines: [{ original_line_id: line, taxable: "25" }] })).id;
  await call("post", `/documents/${invoice}/credit-notes`, { reason: "goods_returned", stock_treatment: "restock", lines: [{ original_line_id: line, quantity: "1" }] });
  const draft = (await call("post", "/drafts", { kind: "invoice", customer_id: customer, lines })).id;
  const returns = (await call("get", "/returns")).returns as { form: string; instance_id: string }[];
  const gstr1 = returns.find((r) => r.form === "GSTR1")!.instance_id;
  const gstr3b = returns.find((r) => r.form === "GSTR3B")!.instance_id;
  return { customer, product, invoice, note, draft, gstr1, gstr3b };
}

test("every screen passes axe with data in it", async ({ page }, info) => {
  test.setTimeout(300_000);
  await signUp(page, `e2e-a11y-${info.project.name}-${Date.now()}@example.com`);
  await createBusiness(page);
  const businessId = page.url().match(/\/b\/([0-9a-f-]{36})\//)![1];
  const s = await seed(page, businessId);
  const b = `/b/${businessId}`;
  const screens: [string, string][] = [
    ["Home", `${b}/home`],
    ["New invoice", `${b}/invoices/new`],
    ["Draft invoice", `${b}/invoices/${s.draft}`],
    ["Draft invoices", `${b}/drafts`],
    ["Issued invoices", `${b}/documents`],
    ["Issued invoice", `${b}/documents/${s.invoice}`],
    ["Debit note by amount", `${b}/documents/${s.note}`],
    ["Adjust invoice", `${b}/documents/${s.invoice}/adjust`],
    ["Customers", `${b}/customers`],
    ["New customer", `${b}/customers/new`],
    ["Customer", `${b}/customers/${s.customer}`],
    ["Products", `${b}/products`],
    ["New product", `${b}/products/new`],
    ["Product", `${b}/products/${s.product}`],
    ["Import products", `${b}/products/import`],
    ["Stock", `${b}/stock`],
    ["Purchase invoices", `${b}/purchases`],
    ["Your GST filing", `${b}/filing`],
    ["GSTR-1: checks", `${b}/filing/${s.gstr1}?tab=checks`],
    ["GSTR-1: contents", `${b}/filing/${s.gstr1}?tab=contents`],
    ["GSTR-1: documents issued", `${b}/filing/${s.gstr1}?tab=documents`],
    ["GSTR-1: file", `${b}/filing/${s.gstr1}?tab=file`],
    ["GSTR-1 portal guide", `${b}/filing/${s.gstr1}/portal-guide`],
    ["GSTR-3B worksheet", `${b}/filing/${s.gstr3b}/worksheet`],
    ["GSTR-3B portal guide", `${b}/filing/${s.gstr3b}/portal-guide-3b`],
    ["Upload your reports", `${b}/uploads`],
    ["File from own invoices", `${b}/file-period`],
    ["Monthly and quarterly files", `${b}/period-files`],
    ["Business setup", `${b}/settings`],
    ["Invoice numbering", `${b}/settings/numbering`],
    ["Invoicing plan", `${b}/settings/plan`],
    ["Your team", `${b}/settings/team`],
    ["Audit log", `${b}/settings/audit`],
    ["Two-step sign-in", `${b}/settings/security`],
    ["Support access", `${b}/settings/support`],
    ["Marketplaces", `${b}/onboarding/marketplaces`],
    ["Your businesses", `/businesses`],
  ];
  const serious: string[] = [];
  const lesser: string[] = [];
  for (const [name, path] of screens) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
    await expect(page.getByText("Loading…")).toHaveCount(0, { timeout: 10_000 });
    await expect(page.getByText("Something went wrong on our side"), `${name} failed to load`).toHaveCount(0);
    const { violations } = await new AxeBuilder({ page }).analyze();
    for (const v of violations) {
      const where = v.nodes.slice(0, 2).map((n) => n.target.join(" ")).join(" | ");
      (v.impact === "serious" || v.impact === "critical" ? serious : lesser).push(`${name}: [${v.impact}] ${v.id}: ${v.help} (${where})`);
    }
  }
  if (lesser.length) console.log(`moderate/minor axe findings (${info.project.name}):\n${lesser.join("\n")}`);
  expect(serious).toEqual([]);
});
