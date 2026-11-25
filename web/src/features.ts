/**
 * Build-time feature flags. R1 is onboarding and GST filing for online sellers, so invoicing
 * is off; Release 2 turns it on. A flag only hides screens: the server still decides what a
 * user may do, and a hidden route answers with the not-found page.
 */
export const FEATURES = {
  invoicing: true, // the Sell card on Home and the /invoices screens (R2)
  // Invoice numbering is off until the CA confirms it (D-010): every invoice is a practice one,
  // and the top bar says "Practice mode".
  practiceOnly: true,
} as const;
