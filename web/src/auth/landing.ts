export type Membership = {
  business_id: string;
  display_name: string;
  gstin: string | null;
  role: string;
  /** Only on a support user's list: when the grant that lets them in ends (LLD-2 §6.2). */
  support_ends_at?: string;
};

/** LLD-1 §11.2: no business → onboarding; one → its Home; more → the picker. Support staff
 * hold no memberships (AC2-14) and land on their own list of businesses instead. */
export function landingPath(memberships: Membership[], isSupport = false): string {
  if (isSupport) return "/support";
  if (memberships.length === 0) return "/onboarding/business";
  if (memberships.length === 1) return `/b/${memberships[0].business_id}/home`;
  return "/businesses";
}
