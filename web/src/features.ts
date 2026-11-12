/**
 * Build-time feature flags. R1 is onboarding and GST filing for online sellers, so invoicing
 * is off; Release 2 turns it on. A flag only hides screens: the server still decides what a
 * user may do, and a hidden route answers with the not-found page.
 */
export const FEATURES = {
  invoicing: false, // the Sell card on Home and the /invoices screens (R2)
} as const;
