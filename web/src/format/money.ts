// Amounts arrive as decimal strings and are shown from the string alone: never through
// Number, so nothing is rounded by binary floating point (CLAUDE.md rule 7).

/** "123456.5" as "₹1,23,456.50" (Indian grouping, two decimals). A malformed value is shown as is. */
export function formatRupees(amount: string): string {
  const m = /^\s*(-?)(\d+)(?:\.(\d+))?\s*$/.exec(amount);
  if (!m) return amount;
  const [, sign, whole, fraction = ""] = m;
  if (fraction.length > 2 && /[1-9]/.test(fraction.slice(2))) return amount; // not ours to round
  const digits = whole.replace(/^0+(?=\d)/, "");
  const last3 = digits.slice(-3);
  const rest = digits.slice(0, -3).replace(/\B(?=(\d{2})+$)/g, ",");
  return `${sign}₹${rest ? `${rest},` : ""}${last3}.${fraction.slice(0, 2).padEnd(2, "0")}`;
}

/** A GST rate string such as "18" or "0.25" as "18%". */
export function formatRate(rate: string): string {
  return /^\d+(\.\d+)?$/.test(rate.trim()) ? `${rate.trim()}%` : rate;
}
