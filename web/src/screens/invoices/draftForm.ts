import type { components } from "../../api/schema";

export type DraftIn = components["schemas"]["DraftIn"];
export type Draft = components["schemas"]["DraftOut"];

export type Line = {
  key: string;
  product_id: string;
  name: string;
  quantity: string;
  unit_price: string; // blank: the server uses the product's sale rate
  discount_kind: "" | "amount" | "percent";
  discount_value: string;
};
type Address = { name: string; line1: string; line2: string; city: string; pin: string; state_code: string };
export type Form = {
  buyer: "customer" | "cash";
  customer_id: string;
  customer_name: string;
  cash_state: string;
  cash_name: string;
  cash_address: string;
  doc_date: string;
  invoice_discount: string;
  charges: { label: string; amount: string }[];
  lines: Line[];
  customer_collects: boolean;
  ship_different: boolean;
  ship: Address;
  third_party: boolean;
  pos_override: string;
  pos_reason: string;
};

const BLANK_ADDRESS: Address = { name: "", line1: "", line2: "", city: "", pin: "", state_code: "" };
export const newLine = (): Line => ({ key: crypto.randomUUID(), product_id: "", name: "", quantity: "1", unit_price: "", discount_kind: "", discount_value: "" });

export const blankForm = (): Form => ({
  buyer: "customer", customer_id: "", customer_name: "", cash_state: "", cash_name: "", cash_address: "",
  doc_date: "", invoice_discount: "0", charges: [], lines: [], customer_collects: false,
  ship_different: false, ship: BLANK_ADDRESS, third_party: false, pos_override: "", pos_reason: "",
}); // fmt: skip

const text = (v: unknown) => (typeof v === "string" ? v : "");

/** The form a saved draft opens as; `names` maps product IDs to the names the page has. */
export function formOf(d: Draft, names: Record<string, string> = {}): Form {
  const cash = d.cash_buyer as Record<string, unknown> | null;
  const ship = d.ship_to as Record<string, unknown> | null;
  return {
    buyer: d.customer_id || !cash ? "customer" : "cash",
    customer_id: d.customer_id ?? "",
    customer_name: text((d.bill_to as Record<string, unknown> | null)?.name),
    cash_state: text(cash?.state_code),
    cash_name: text(cash?.name),
    cash_address: text(cash?.address),
    doc_date: d.doc_date ?? "",
    invoice_discount: d.invoice_discount,
    charges: d.charges as { label: string; amount: string }[],
    lines: d.lines.map((l) => ({
      key: l.id, product_id: l.product_id, name: names[l.product_id] ?? "", quantity: l.quantity, unit_price: l.unit_price,
      discount_kind: (l.discount_kind ?? "") as Line["discount_kind"], discount_value: l.discount_value ?? "",
    })),
    customer_collects: d.customer_collects,
    ship_different: Boolean(ship),
    ship: ship ? { name: text(ship.name), line1: text(ship.line1), line2: text(ship.line2), city: text(ship.city), pin: text(ship.pin), state_code: text(ship.state_code) } : BLANK_ADDRESS,
    third_party: d.ship_to_third_party,
    pos_override: d.pos_override ?? "",
    pos_reason: d.pos_override_reason ?? "",
  }; // fmt: skip
}

const orNull = (v: string) => v.trim() || null;

/** The body the server takes. Only the amounts typed are sent; every figure comes back from it. */
export function draftIn(f: Form): DraftIn {
  const cash = f.buyer === "cash";
  const ship = f.ship_different && !f.customer_collects;
  return {
    kind: "invoice",
    customer_id: cash ? null : f.customer_id || null,
    cash_buyer: cash ? { state_code: f.cash_state, name: orNull(f.cash_name), address: orNull(f.cash_address) } : null,
    doc_date: f.doc_date || null,
    invoice_discount: f.invoice_discount.trim() || "0",
    charges: f.charges.filter((c) => c.label.trim() || c.amount.trim()).map((c) => ({ label: c.label.trim(), amount: c.amount.trim() })),
    lines: f.lines.map((l) => ({
      product_id: l.product_id,
      quantity: l.quantity.trim(),
      unit_price: orNull(l.unit_price),
      discount_kind: l.discount_kind || null,
      discount_value: l.discount_kind ? orNull(l.discount_value) : null,
    })),
    customer_collects: f.customer_collects,
    ship_to: ship
      ? { state_code: f.ship.state_code, name: orNull(f.ship.name), line1: orNull(f.ship.line1), line2: orNull(f.ship.line2), city: orNull(f.ship.city), pin: orNull(f.ship.pin) }
      : null,
    ship_to_third_party: ship && f.third_party,
    pos_override: orNull(f.pos_override),
    pos_override_reason: f.pos_override.trim() ? orNull(f.pos_reason) : null,
  };
}

/** True when the form would save something different from what was last saved. */
export const sameForm = (a: Form, b: Form) => JSON.stringify(draftIn(a)) === JSON.stringify(draftIn(b));
