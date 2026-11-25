import type { components } from "../../api/schema";
import { formatRate, formatRupees } from "../../format/money";

type Product = components["schemas"]["ProductOut"];

const CATEGORY: Record<string, string> = { exempt: "Exempt", nil_rated: "Nil rated", non_gst: "Non-GST" };

/** "HSN 3305", or "HSN missing" (mocks v16 line details). */
export const hsnText = (hsn: string | null | undefined) => (hsn ? `HSN ${hsn}` : "HSN missing");

/** "GST 18%" for a taxable product with a rate on record, its treatment otherwise. Display only. */
export function gstText(p: Pick<Product, "tax_category" | "rate_on">): string {
  if (p.tax_category !== "taxable") return CATEGORY[p.tax_category] ?? p.tax_category;
  return p.rate_on ? `GST ${formatRate(p.rate_on.rate.replace(/\.0+$|(\.\d*?)0+$/, "$1"))}` : "GST rate not set";
}

/** MRP is shown for reference only (D-104): "—" when the product has none. Tax always comes from the rate. */
export const mrpText = (mrp: string | null | undefined) => (mrp ? formatRupees(mrp) : "—");
