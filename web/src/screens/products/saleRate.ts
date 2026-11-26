/**
 * What is wrong with the text in a sale-rate or price box, or undefined when nothing is. The box keeps exactly
 * what was typed or pasted and the person is told what to change: a price never changes without being seen
 * (a dropped decimal or minus sign would have saved a different price). Text only, no arithmetic: the value is
 * sent to the server as the string it is, and the server's rule is `^[0-9]{1,16}(\.[0-9]{1,2})?$`.
 *
 * While someone is still typing, "10." is not a problem yet; pass `final` when they save.
 */
export function saleRateProblem(raw: string, final = false): string | undefined {
  const text = raw.trim();
  if (!text) return undefined;
  if (text.includes("-")) return "A price can't be negative.";
  if (!/^[0-9.]+$/.test(text) || (text.match(/\./g) ?? []).length > 1) return "Enter a number, like 45 or 45.50.";
  const [whole, decimals] = text.split(".");
  if (decimals !== undefined && decimals.length > 2) return "Use at most 2 decimal places.";
  if (whole.length > 16) return "That number is too large.";
  if (final && (whole === "" || decimals === "")) return "Enter a number, like 45 or 45.50.";
  return undefined;
}

/** The same for the MRP (#398), required since D-107: the server keeps 12 digits before the point (numeric(14, 2)). */
export function mrpProblem(raw: string, final = false): string | undefined {
  if (final && !raw.trim()) return "Enter the MRP, the price per unit with GST included.";
  const problem = saleRateProblem(raw, final);
  if (problem) return problem.replace("A price", "An MRP");
  return raw.trim().split(".")[0].length > 12 ? "That number is too large." : undefined;
}

/** A decimal string as an integer scaled by 10^places, or null if it is not a plain non-negative decimal with at most that many places. */
function scaled(text: string, places: number): bigint | null {
  const t = text.trim();
  const m = /^([0-9]*)(?:\.([0-9]*))?$/.exec(t);
  if (!m || t === "" || t === "." || (m[2] ?? "").length > places) return null;
  return BigInt((m[1] || "0") + (m[2] ?? "").padEnd(places, "0"));
}

/**
 * The sale rate an MRP implies (D-107): MRP / (1 + GST%/100), half up to the paisa, the same rule as the server's
 * `rate_from_mrp`. Whole-number arithmetic (paise and thousandths of a percent), never floating point. A product outside
 * GST has no GST in its MRP, so the rate is the MRP. Null when the MRP or the GST rate can't be read yet. A form helper
 * only: the server works the invoice line's rate out again.
 */
export function rateFromMrp(mrp: string, gstRate: string | null | undefined, taxable: boolean): string | null {
  const paise = scaled(mrp, 2);
  if (paise === null) return null;
  let out = paise;
  if (taxable) {
    const rate = gstRate ? scaled(gstRate, 3) : null; // 18 -> 18000, 0.25 -> 250
    if (rate === null) return null;
    const num = paise * 100000n;
    const den = 100000n + rate;
    out = (2n * num + den) / (2n * den); // half up
  }
  const s = out.toString().padStart(3, "0");
  return `${s.slice(0, -2)}.${s.slice(-2)}`;
}
