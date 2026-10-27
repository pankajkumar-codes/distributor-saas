export type Membership = { business_id: string; display_name: string; gstin: string | null; role: string };

/** LLD-1 §11.2: no business → onboarding; one → its Home; more → the picker. */
export function landingPath(memberships: Membership[]): string {
  if (memberships.length === 0) return "/onboarding/business";
  if (memberships.length === 1) return `/b/${memberships[0].business_id}/home`;
  return "/businesses";
}
