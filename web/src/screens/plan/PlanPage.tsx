import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { formatRupees } from "../../format/money";
import { Banner } from "../../kit/Banner";
import { NotFound } from "../../kit/NotFound";
import { TopBar } from "../../kit/TopBar";

type Plan = components["schemas"]["InvoicingPlanOut"];

/**
 * The invoicing plan (R2-M7): the first free invoices and how many are left, and the plan's prices. While payments
 * are a placeholder the server says "free for now" and nothing is charged. Every figure is the server's.
 */
export function PlanPage() {
  const { businessId = "" } = useParams();
  const businesses = useMyBusinesses();
  const business = businesses.data?.find((b) => b.business_id === businessId);
  const plan = useQuery<Plan, ApiError>({
    queryKey: ["b", businessId, "invoicing-plan"],
    enabled: Boolean(business),
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/invoicing-plan", { params: { path: { business_id: businessId } } })),
  });

  if (businesses.isPending) {
    return (
      <main className="page" aria-busy="true">
        <p>Loading…</p>
      </main>
    );
  }
  if (!business) return <NotFound />;
  const p = plan.data;

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page">
        <p className="step">
          <Link to={`/b/${businessId}/home`}>Home</Link>
        </p>
        <h1>Invoicing plan</h1>
        {plan.error && <Banner tone="error">{errorText(plan.error)}</Banner>}
        {plan.isPending && <p aria-busy="true">Loading…</p>}
        {p && (
          <>
            <section aria-labelledby="free-count">
              <h2 id="free-count">Your free invoices</h2>
              <p>
                <strong>
                  {p.used} of {p.free_invoices}
                </strong>{" "}
                used · {p.remaining_free} left
              </p>
              <p className="hint">Practice invoices count too.</p>
              {p.needs_plan && !p.free_for_now && <Banner tone="error">You have used your free invoices. Choose a plan to keep creating invoices.</Banner>}
            </section>
            <section aria-labelledby="plan-name">
              <h2 id="plan-name">{p.name}</h2>
              {p.free_for_now ? (
                <p>
                  <strong>Free for now.</strong> Nothing is charged at the moment. These are the prices once plans start:
                </p>
              ) : (
                <p>Prices:</p>
              )}
              <ul className="list">
                <li>Monthly: {formatRupees(String(p.monthly_rupees))}</li>
                <li>Quarterly: {formatRupees(String(p.quarterly_rupees))}</li>
              </ul>
              <p className="hint">{p.gst_note}</p>
            </section>
          </>
        )}
      </main>
    </>
  );
}
