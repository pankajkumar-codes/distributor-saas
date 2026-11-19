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
