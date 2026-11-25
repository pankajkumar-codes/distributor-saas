import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { formatRupees } from "../../format/money";
import { Banner } from "../../kit/Banner";
import { NotFound } from "../../kit/NotFound";
import { TopBar } from "../../kit/TopBar";
import { PageHead } from "../../kit/PageHead";
import { Loading } from "../../kit/Loading";

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
      <main className="page page-wide">
        <PageHead
          crumbs={[{ label: "Settings", to: `/b/${businessId}/settings` }, { label: "Invoicing plan" }]}
          title="Invoicing plan"
          sub={p?.free_for_now ? "Free for now. Payments are not switched on yet." : undefined}
        />
        {plan.error && <Banner tone="error">{errorText(plan.error)}</Banner>}
        {plan.isPending && <Loading query={plan} />}
        {p && (
          <div className="cols2 plan-cols">
            <section className="panel" aria-labelledby="free-count">
              <div className="panel-h">
                <h2 id="free-count">Your free invoices</h2>
                <span className={p.remaining_free > 0 ? "chip chip-ok" : "chip chip-warn"}>{p.remaining_free} left</span>
              </div>
              <div className="pad">
                <p className="plan-used">
                  <strong className="num">{p.used}</strong> <span className="num">of {p.free_invoices} used</span>
                </p>
                <div className="home-bar" aria-hidden="true">
                  <i style={{ width: `${Math.min(100, p.free_invoices ? (p.used / p.free_invoices) * 100 : 0)}%` }} />
                </div>
                <p className="hint">Practice invoices count too.</p>
                {p.needs_plan && !p.free_for_now && <Banner tone="error">You have used your free invoices. Choose a plan to keep creating invoices.</Banner>}
              </div>
            </section>
            <section className="panel" aria-labelledby="plan-name">
              <div className="panel-h">
                <h2 id="plan-name">{p.free_for_now ? `${p.name}: prices once plans start` : p.name}</h2>
              </div>
              <dl className="kvs">
                <div>
                  <dt>Monthly</dt>
                  <dd className="num">{formatRupees(String(p.monthly_rupees))}</dd>
                </div>
                <div>
                  <dt>Quarterly</dt>
                  <dd className="num">{formatRupees(String(p.quarterly_rupees))}</dd>
                </div>
                <div>
                  <dt>GST on the plan</dt>
                  <dd>{p.gst_note}</dd>
                </div>
              </dl>
            </section>
          </div>
        )}
      </main>
    </>
  );
}
