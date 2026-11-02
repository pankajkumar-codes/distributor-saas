import { useQuery } from "@tanstack/react-query";
import { Link, useLocation, useParams } from "react-router-dom";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { formatDate, hourIst } from "../../format/dates";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { NotFound } from "../../kit/NotFound";
import { TopBar } from "../../kit/TopBar";
import { warningText } from "../onboarding/warnings";
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
const SEVERITY = { block: "Needs action", warn: "Check", info: "For your information" } as const;

export function greeting(name: string | null | undefined, now = new Date()): string {
  if (!name) return "Welcome";
  const hour = hourIst(now);
  return `Good ${hour < 12 ? "morning" : hour < 17 ? "afternoon" : "evening"}, ${name}`;
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
  const nudges = (data?.attention ?? []).map(asNudge).filter((n): n is Nudge => n !== null);

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page">
        <h1>{greeting(data?.greeting_name)}</h1>
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
              {nudges.map((n) => {
                const to = screenPath(n.href, businessId);
                return (
                  <li key={n.key} className={`nudge nudge-${n.severity}`}>
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

        {data && data.checklist.done < data.checklist.total && (
          <section className="card" aria-labelledby="setup">
            <h2 id="setup">Set up your business</h2>
            <p className="hint">
              {data.checklist.done} of {data.checklist.total} done
            </p>
            <ul className="list">
              {items.map((item) => {
                const to = screenPath(item.href, businessId);
                return (
                  <li key={item.key} className="check">
                    <span aria-hidden="true">{item.done ? "✓" : "○"}</span>{" "}
                    {item.done || !to ? <span>{ITEMS[item.key]}</span> : <Link to={to}>{ITEMS[item.key]}</Link>}
                    <span className="visually-hidden">{item.done ? " (done)" : " (not done)"}</span>
                    {!item.done && !to && <span className="tag"> Coming soon</span>}
                  </li>
                );
              })}
            </ul>
          </section>
        )}
      </main>
    </>
  );
}
