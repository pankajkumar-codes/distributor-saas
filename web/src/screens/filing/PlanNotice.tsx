import { Banner } from "../../kit/Banner";
import { usePlan } from "./plan";

const rupees = (n: number) => `₹${n.toLocaleString("en-IN")}`;

/**
 * The plan and its prices next to the file (R1-M9). While the server says `free_for_now` nothing is charged and no payment
 * is asked for: the prices are shown so people know what is coming. The wording "free for now" comes only from that flag.
 * If the plan can't be read the panel shows nothing; the server still decides whether the file may be made.
 */
export function PlanNotice({ businessId }: { businessId: string }) {
  const plan = usePlan(businessId).data;
  if (!plan) return null;
  return (
    <div className="stack" aria-label="Your plan">
      <h3>{plan.name} plan</h3>
      <p>
        {rupees(plan.monthly_rupees)} a month, or {rupees(plan.quarterly_rupees)} a quarter, {plan.gst_note}.
      </p>
      {plan.free_for_now && <Banner>This is free for now. You will not be charged, and we will tell you before that changes.</Banner>}
    </div>
  );
}
