/**
 * What a sale-rate box keeps as someone types or pastes: digits and one decimal point, up to 16 digits
 * and 2 decimals (the server's rule, `^[0-9]{1,16}(\.[0-9]{1,2})?$`). Letters, signs and spaces are dropped.
 * Text only, no arithmetic: the value is sent to the server as the string it is.
 */
export function saleRateText(raw: string): string {
  const kept = raw.replace(/[^0-9.]/g, "");
  const dot = kept.indexOf(".");
  if (dot === -1) return kept.slice(0, 16);
  const whole = kept.slice(0, dot).slice(0, 16);
  const decimals = kept.slice(dot + 1).replace(/\./g, "").slice(0, 2);
  return `${whole}.${decimals}`;
}
