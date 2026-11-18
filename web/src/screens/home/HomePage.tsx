import { useQuery } from "@tanstack/react-query";
import { Link, useLocation, useParams } from "react-router-dom";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { canCreateDocuments, canPrepareReturns, canViewUploads } from "../../auth/roles";
import { FEATURES } from "../../features";
import { TOTP_PROMPTED, useMe } from "../../auth/useMe";
import { SUPPORT_ROLE, useMyBusinesses } from "../../auth/useMyBusinesses";
import { formatDate } from "../../format/dates";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { NotFound } from "../../kit/NotFound";
import { TopBar } from "../../kit/TopBar";
import { useReturns } from "../filing/returns";
import { warningText } from "../onboarding/warnings";
import { AUDIT_VIEWERS } from "../settings/AuditPage";
import { SUPPORT_VIEWERS } from "../settings/SupportPage";
import { screenPath } from "./links";

type Home = components["schemas"]["HomeOut"];
// LLD-6 §3. The API types it as a plain object until insights (S6) gives it a model.
type Nudge = { key: string; severity: "block" | "warn" | "info"; title: string; detail?: string; due?: string; href?: string };

// M3's order and words, pending the Designer and PO (OPEN_QUESTIONS). A key the web doesn't
// know yet is left out rather than shown without a label.
const ITEMS: Record<string, string> = {
  business_profile: "Business details",
  filing_frequency: "Filing frequency",
  marketplaces: "Marketplaces you sell on",
  first_product: "Add your first product",
  first_customer: "Add your first customer",
  invite_ca_or_teammate: "Invite your CA or a teammate",
};
const FORMS: Record<string, string> = { GSTR1: "GSTR-1", GSTR3B: "GSTR-3B" };
const SEVERITY = { block: "Needs action", warn: "Check", info: "For your information" } as const;

export function greeting(name: string | null | undefined): string {
  return name ? `Welcome, ${name}` : "Welcome";
}

function asNudge(row: Record<string, unknown>): Nudge | null {
  const { key, severity, title } = row;
  if (typeof key !== "string" || typeof title !== "string") return null;
  if (severity !== "block" && severity !== "warn" && severity !== "info") return null;
  const text = (v: unknown) => (typeof v === "string" ? v : undefined);
  return { key, severity, title, detail: text(row.detail), due: text(row.due), href: text(row.href) };
}

/**
 * M3 Home (LLD-1 §10). The business ID in the URL is only a hint: the server decides access
 * on every call, and a business not in /me/businesses is the same NotFound as one that
 * doesn't exist (LLD-1 §11.2). Cards for parts the server sends as null stay hidden.
 */
export function HomePage() {
  const { businessId = "" } = useParams();
  const businesses = useMyBusinesses();
  const business = businesses.data?.find((b) => b.business_id === businessId);
  const home = useQuery<Home, ApiError>({
    queryKey: ["b", businessId, "home"],
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/home", { params: { path: { business_id: businessId } } })),
    enabled: Boolean(business),
  });
  // The GST card shows the server's current periods (the same call as Filing home; only for roles that may prepare returns, the others would get a 403); if it fails the card just has the button.
  const returns = useReturns(businessId, undefined, Boolean(business) && canPrepareReturns(business?.role ?? ""));
  // Owners and CAs are asked to turn on two-step sign-in (H-1 item 3); nobody else is asked.
  const me = useMe({ enabled: Boolean(business && TOTP_PROMPTED.has(business.role)) });
  // Warnings from creating the business, handed over by /onboarding/business; gone on reload.
  const state = useLocation().state as { warnings?: unknown } | null;
  const warnings = Array.isArray(state?.warnings) ? state.warnings.filter((w): w is string => typeof w === "string") : [];

  if (businesses.isPending) {
    return (
      <main className="page" aria-busy="true">
        <p>Loading…</p>
      </main>
    );
  }
  if (businesses.error) {
    return (
      <main className="page">
        <Banner tone="error">{errorText(businesses.error)}</Banner>
      </main>
    );
  }
  if (!business) return <NotFound />;

  const data = home.data;
  const items = (data?.checklist.items ?? []).filter((i) => i.key in ITEMS);
  // The first return still to do for each form, in the server's order; due dates only when the server has confirmed them.
  const filingRows = ["GSTR1", "GSTR3B"]
    .map((f) => returns.data?.returns.find((r) => r.form === f && (r.status === "open" || r.status === "unlocked")))
    .filter((r): r is NonNullable<typeof r> => r !== undefined);
  const nudges = (data?.attention ?? []).map(asNudge).filter((n): n is Nudge => n !== null);

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page page-wide">
        <h1>{greeting(data?.greeting_name)}</h1>
        <p className="hint home-sub">Here is where your business stands today.</p>
        {warnings.length > 0 && (
          <Banner>
            <p>Your business is saved. Please check:</p>
            <ul>
              {[...new Set(warnings)].map((w) => (
                <li key={w}>{warningText(w)}</li>
              ))}
            </ul>
          </Banner>
        )}
        {home.isPending && <p aria-busy="true">Loading…</p>}
        {home.error && (
          <Banner tone="error">
            {errorText(home.error)}{" "}
            <Button type="button" variant="link" onClick={() => home.refetch()}>
              Try again
            </Button>
          </Banner>
        )}

        {nudges.length > 0 && (
          <section className="card" aria-labelledby="attention">
            <h2 id="attention">Needs your attention</h2>
            <ul className="list">
              {nudges.map((n, i) => {
                const to = screenPath(n.href, businessId);
                return (
                  <li key={`${n.key}-${i}`} className={`nudge nudge-${n.severity}`}>
                    <strong>
                      <span className="tag">{SEVERITY[n.severity]}</span> {n.title}
                    </strong>
                    {n.detail && <p className="hint">{n.detail}</p>}
                    {n.due && <p className="hint">Due {formatDate(n.due)}</p>}
                    {to && <Link to={to}>Fix this</Link>}
                  </li>
                );
              })}
            </ul>
          </section>
        )}

        <div className="home-cols">
          <div className="home-col">
            {data && data.checklist.done < data.checklist.total && (
              <section className="card" aria-labelledby="setup">
                <div className="between">
                  <h2 id="setup">Set up your business</h2>
                  <span className="hint">
                    {data.checklist.done} of {data.checklist.total} done
                  </span>
                </div>
                <div className="home-bar" aria-hidden="true">
                  <i style={{ width: `${(data.checklist.done / Math.max(data.checklist.total, 1)) * 100}%` }} />
                </div>
                <ul className="home-steps">
                  {items.map((item, i) => {
                    const to = screenPath(item.href, businessId);
                    const state = item.done ? "done" : to ? "now" : "later";
                    return (
                      <li key={item.key}>
                        <span className={`home-dot ${state}`} aria-hidden="true">
                          {item.done ? "✓" : i + 1}
                        </span>
                        <span className={state === "now" ? undefined : "muted"}>
                          {state === "now" && to ? <Link to={to}>{ITEMS[item.key]}</Link> : ITEMS[item.key]}
                          <span className="visually-hidden">{item.done ? " (done)" : " (not done)"}</span>
                        </span>
                        {item.done ? (
                          <span className="hint">Done</span>
                        ) : to ? (
                          <span className="chip chip-warn">To do</span>
                        ) : (
                          <span className="up">Upcoming</span>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </section>
            )}
            {/* Until the app has its own navigation (Designer, OPEN_QUESTIONS), Home is the way in. */}
            {FEATURES.invoicing && canCreateDocuments(business.role) && (
              <nav className="card" aria-labelledby="sell">
                <h2 id="sell">Sell</h2>
                <ul className="list">
                  <li>
                    <Link to={`/b/${businessId}/invoices/new`}>New invoice</Link>
                  </li>
                  <li>
                    <Link to={`/b/${businessId}/documents`}>Issued invoices</Link>
                  </li>
                  {canViewUploads(business.role) && ( // purchases are owner, admin and CA; billing would get a 404
                    <li>
                      <Link to={`/b/${businessId}/purchases`}>Purchase invoices</Link>
                    </li>
                  )}
                  <li>
                    <Link to={`/b/${businessId}/stock`}>Stock</Link>
                  </li>
                  <li>
                    <Link to={`/b/${businessId}/settings/plan`}>Invoicing plan</Link>
                  </li>
                </ul>
              </nav>
            )}
          </div>

          <div className="home-col">
            {canPrepareReturns(business.role) && ( // billing is turned away from the filing pages
              <nav className="card" aria-labelledby="filing">
                <div className="between">
                  <h2 id="filing">GST filing</h2>
                  {returns.data?.filing_frequency && (
                    <span className="chip chip-info">{returns.data.filing_frequency === "quarterly" ? "Quarterly" : "Monthly"}</span>
                  )}
                </div>
                {filingRows.map((r) => (
                  <div className="kv" key={r.instance_id}>
                    <span>
                      {FORMS[r.form]} · {r.period_label}
                    </span>
                    <span className="hint">
                      {r.due_date && r.due_date_confirmed ? `Due ${formatDate(r.due_date)}` : "Due date: check Filing home"}
                    </span>
                  </div>
                ))}
                <div className="home-actions">
                  <Link className="btn btn-primary" to={`/b/${businessId}/filing`}>
                    Open Filing home
                  </Link>
                  {FEATURES.invoicing && canPrepareReturns(business.role) && (
                    <Link to={`/b/${businessId}/file-period`}>File from your own invoices</Link>
                  )}
                  {canViewUploads(business.role) && <Link to={`/b/${businessId}/uploads`}>Upload your reports</Link>}
                </div>
              </nav>
            )}
            {me.data && !me.data.user.totp_enabled && (
              <section className="card" aria-labelledby="totp-prompt">
                <h2 id="totp-prompt">Protect your account</h2>
                <p className="hint">Two-step sign-in asks for a code from your phone as well as your password.</p>
                <Link to={`/b/${businessId}/settings/security`}>Turn on two-step sign-in</Link>
              </section>
            )}
            <nav className="card" aria-labelledby="settings">
              <h2 id="settings">Business setup</h2>
              <p className="hint">Change your business details, where you sell and how often you file.</p>
              <Link to={`/b/${businessId}/settings`}>Open Business setup</Link>
              <div className="home-links">
                {SUPPORT_VIEWERS.has(business.role) && <Link to={`/b/${businessId}/settings/support`}>Support access</Link>}
                {AUDIT_VIEWERS.has(business.role) && <Link to={`/b/${businessId}/settings/audit`}>Audit log</Link>}
                {business.role !== SUPPORT_ROLE && <Link to={`/b/${businessId}/settings/security`}>Two-step sign-in</Link>}
              </div>
            </nav>
          </div>
        </div>
      </main>
    </>
  );
}
