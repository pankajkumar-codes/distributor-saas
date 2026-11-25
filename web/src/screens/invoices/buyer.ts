import type { components } from "../../api/schema";

type Draft = components["schemas"]["DraftPageOut"]["items"][number];

/** Who the draft is for: the customer's name as saved on it, the cash buyer's, or nothing yet. */
export function buyerOf(d: Pick<Draft, "cash_buyer" | "bill_to">): string {
  const name = (v: unknown) => (typeof v === "string" && v.trim() ? v : null);
  if (d.cash_buyer) return name((d.cash_buyer as Record<string, unknown>).name) ?? "Cash sale";
  return name((d.bill_to as Record<string, unknown> | null)?.name) ?? "No buyer yet";
}
