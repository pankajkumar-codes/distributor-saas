import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { canCreateDocuments, canLockReturns, canViewReturns, canViewUploads } from "../../auth/roles";
import { FEATURES } from "../../features";
import { TOTP_PROMPTED, useMe } from "../../auth/useMe";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { formatDate, todayIst } from "../../format/dates";
import { formatRupees } from "../../format/money";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { NotFound } from "../../kit/NotFound";
import { Tabs, type Tab } from "../../kit/Tabs";
import { TopBar } from "../../kit/TopBar";
import { returnKey, useReturns, type ReturnDetail } from "../filing/returns";
import { warningText } from "../onboarding/warnings";
import { buyerOf } from "../invoices/buyer";
import { screenPath } from "./links";
import { daysUntil, dueWords, nextStep, timeline, type NextStep } from "./nextStep";
import { Loading } from "../../kit/Loading";

type Home = components["schemas"]["HomeOut"];
type Drafts = components["schemas"]["DraftPageOut"];
type Documents = components["schemas"]["DocumentsOut"];
// LLD-6 §3. The API types it as a plain object until insights (S6) gives it a model.
type Nudge = { key: string; severity: "block" | "warn" | "info"; title: string; detail?: string; due?: string; href?: string };

const SEVERITY = { block: "Needs action", warn: "Check", info: "For your information" } as const;
const RECENT = 3; // rows in the Recent invoices and Drafts tabs: the whole card stays on one screen

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

const Arrow = () => (
  <svg className="arr" viewBox="0 0 24 24" aria-hidden="true">
    <path d="M5 12h14M13 6l6 6-6 6" />
  </svg>
);

/** "Your next step": where the business is on its path, and one blue button for the current step. */
function NextStepCard({ step }: { step: NextStep }) {
  return (
    <section className="guide" aria-labelledby="next-step">
      <div className="gk">
        <span className="chip chip-blue">Your next step</span>
        {step.current >= 0 && (
          <span>
            Step {step.current + 1} of {step.steps.length}
          </span>
        )}
      </div>
      <h2 id="next-step">{step.title}</h2>
      <p className="hint">{step.hint}</p>
      {step.steps.length > 0 && (
        <ol className="path">
          {step.steps.map((s) => (
            <li key={s.label} className={s.state}>
              <span className="d" aria-hidden="true">
                {s.state === "done" ? "✓" : ""}
              </span>
              <span className="t">
                {s.label}
                <span className="visually-hidden">{s.state === "done" ? " (done)" : s.state === "cur" ? " (current step)" : " (not done)"}</span>
              </span>
              <span className="sub2">{s.sub}</span>
            </li>
          ))}
        </ol>
      )}
      {step.action && (
        <Link className="btn btn-primary" to={step.action.to}>
          {step.action.label} <Arrow />
        </Link>
      )}
    </section>
  );
}

/** Today and the confirmed due dates of this month, as a track; on a phone, as a list. */
function Timeline({ today, rows, period, frequency }: { today: string; rows: { form: string; due_date?: string | null; due_date_confirmed: boolean }[]; period?: string; frequency?: string | null }) {
  const t = timeline(today, rows);
  const pct = (x: number) => `${(x * 100).toFixed(2)}%`;
  return (
    <section className="panel tl" aria-labelledby="timeline">
      <div className="between">
        <h2 id="timeline">{t.month}</h2>
        {period && (
          <span className="hint">
            Filing for {period}
            {frequency ? ` · ${frequency}` : ""}
          </span>
        )}
      </div>
      <div className="tl-track" aria-hidden="true">
        <div className="tl-line" />
        <div className="tl-fill" style={{ width: pct(t.todayAt) }} />
        {t.onTrack.map((k) => (
          <div key={k.key} className={`tl-m ${k.due ? "due" : "today"}`} style={{ left: pct(k.at) }}>
            <span className="lab">{k.label}</span>
            <span className="d" />
            <span className="sub num">{formatDate(k.day).slice(0, 6)}</span>
          </div>
        ))}
      </div>
      <dl className="tl-list">
        {t.markers.map((k) => (
          <div key={k.key}>
            <dt>{k.due ? `${k.label} due` : k.label}</dt>
            <dd className="num">
              {formatDate(k.day)}
              {k.due ? ` · ${dueWords(daysUntil(k.day, today))}` : ""}
            </dd>
          </div>
        ))}
      </dl>
      {t.markers.length === 1 && <p className="hint">Due dates show here once they are confirmed. See Your GST filing.</p>}
    </section>
  );
}

/**
 * Home (mocks v16): the guided "Your next step" card on the left; the month timeline and a tabbed
 * panel (what needs attention, recent invoices, drafts) on the right. The business ID in the URL is
 * only a hint: the server decides access on every call, and a business not in /me/businesses is the
 * same NotFound as one that doesn't exist (LLD-1 §11.2).
 */
export function HomePage() {
  const { businessId = "" } = useParams();
  const businesses = useMyBusinesses();
  const business = businesses.data?.find((b) => b.business_id === businessId);
  const role = business?.role ?? "";
  const [tab, setTab] = useState(0);
  const today = todayIst();
  const home = useQuery<Home, ApiError>({
    queryKey: ["b", businessId, "home"],
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/home", { params: { path: { business_id: businessId } } })),
    enabled: Boolean(business),
  });
  // Only roles that may see returns ask for them; the others would get a 404.
  const filing = Boolean(business) && canViewReturns(role);
  const returns = useReturns(businessId, undefined, filing);
  const open = (form: string) => returns.data?.returns.find((r) => r.form === form && (r.status === "open" || r.status === "unlocked"));
  const gstr1 = open("GSTR1");
  // The read-only build of that return says how far along the path it is (the same read as the return page).
  const build = useQuery<ReturnDetail, ApiError>({
    queryKey: [...returnKey(businessId, gstr1?.instance_id ?? ""), "detail"],
    queryFn: () =>
      call(() =>
        api.GET("/api/v1/b/{business_id}/returns/{instance_id}", { params: { path: { business_id: businessId, instance_id: gstr1?.instance_id ?? "" } } }),
      ),
    enabled: filing && !!gstr1,
    retry: false,
  });
  const before = build.data && build.data.members_count > 0 && !build.data.findings.some((f) => f.level === "block") && build.data.export.to_accept === 0;
  // Whether a file was made, and still matches the return; asked only once the steps before it are done.
  const changes = useQuery({
    queryKey: [...returnKey(businessId, gstr1?.instance_id ?? ""), "changes"],
    queryFn: () =>
      call(() =>
        api.GET("/api/v1/b/{business_id}/returns/{instance_id}/changes", { params: { path: { business_id: businessId, instance_id: gstr1?.instance_id ?? "" } } }),
      ),
    enabled: !!before && canLockReturns(role),
    retry: false,
  });
  const invoicing = FEATURES.invoicing && Boolean(business) && canCreateDocuments(role);
  const drafts = useQuery<Drafts, ApiError>({
    queryKey: ["b", businessId, "drafts", "list", "home"],
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/drafts", { params: { path: { business_id: businessId }, query: { kind: "invoice", limit: RECENT } } })),
    enabled: invoicing,
    retry: false,
  });
  const docs = useQuery<Documents, ApiError>({
    queryKey: ["b", businessId, "drafts", "documents", "home"],
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/documents", { params: { path: { business_id: businessId }, query: { limit: RECENT, offset: 0 } } })),
    enabled: invoicing,
    retry: false,
  });
  // Owners and CAs are asked to turn on two-step sign-in (H-1 item 3); nobody else is asked.
  const me = useMe({ enabled: Boolean(business && TOTP_PROMPTED.has(role)) });
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
  const nudges = (data?.attention ?? []).map(asNudge).filter((n): n is Nudge => n !== null);
  const step = data
    ? nextStep({
        businessId,
        today,
        checklist: data.checklist.items,
        gstr1: filing ? gstr1 : null,
        build: build.data,
        fileTaken: changes.data ? changes.data.reference !== null && changes.data.same : null,
        canUpload: canViewUploads(role),
        canInvoice: invoicing,
      })
    : null;
  const draftRows = drafts.data?.items ?? [];
  const docRows = docs.data?.documents ?? [];
  const totp = me.data && !me.data.user.totp_enabled;
  const attentionCount = nudges.length + (draftRows.length > 0 ? 1 : 0) + (totp ? 1 : 0);
  const count = (n: number, more = false) => (n > 0 ? <span className="chip chip-warn num">{`${n}${more ? "+" : ""}`}</span> : null);

  const attention = (
    <div role="region" aria-label="Needs your attention">
      {attentionCount === 0 && <p className="hint pad">Nothing needs your attention right now.</p>}
      {nudges.map((n, i) => {
        const to = screenPath(n.href, businessId);
        return (
          <div key={`${n.key}-${i}`} className={`issue${n.severity === "block" ? " bad" : ""}`}>
            <span className="ic" aria-hidden="true">
              {n.severity === "info" ? "i" : "!"}
            </span>
            <div className="tx">
              <b>
                <span className="visually-hidden">{SEVERITY[n.severity]}: </span>
                {n.title}
              </b>
              {(n.detail || n.due) && (
                <span>
                  {n.detail}
                  {n.detail && n.due ? " · " : ""}
                  {n.due && `Due ${formatDate(n.due)}`}
                </span>
              )}
            </div>
            {to && (
              <Link className="btn btn-secondary btn-sm" to={to}>
                Fix this
              </Link>
            )}
          </div>
        );
      })}
      {draftRows.length > 0 && (
        <div className="issue">
          <span className="ic" aria-hidden="true">
            !
          </span>
          <div className="tx">
            <b>{drafts.data?.has_more ? "Draft invoices not finished" : draftRows.length === 1 ? "1 draft invoice not finished" : `${draftRows.length} draft invoices not finished`}</b>
          </div>
          <Link className="btn btn-secondary btn-sm" to={`/b/${businessId}/drafts`}>
            Open drafts
          </Link>
        </div>
      )}
      {totp && (
        <div className="issue">
          <span className="ic" aria-hidden="true">
            i
          </span>
          <div className="tx">
            <b>Protect your account with two-step sign-in</b>
          </div>
          <Link className="btn btn-secondary btn-sm" to={`/b/${businessId}/settings/security`}>
            Turn on
          </Link>
        </div>
      )}
    </div>
  );

  const tabs: Tab[] = [{ label: <>Needs your attention {count(attentionCount)}</>, panel: attention }];
  if (invoicing) {
    tabs.push({
      label: "Recent invoices",
      panel: (
        <>
          {docs.error && <p className="hint pad">{errorText(docs.error)}</p>}
          {docs.isSuccess && docRows.length === 0 && <p className="hint pad">No invoices issued yet.</p>}
          {docRows.length > 0 && (
            <table className="products">
              <thead>
                <tr>
                  <th scope="col">Invoice</th>
                  <th scope="col">Buyer</th>
                  <th scope="col" className="r">
                    Total
                  </th>
                </tr>
              </thead>
              <tbody>
                {docRows.map((d) => (
                  <tr key={d.id}>
                    <td data-label="Invoice" className="num">
                      <Link to={`/b/${businessId}/documents/${d.id}`}>{d.doc_number}</Link> <span className="sub2">{formatDate(d.doc_date)}</span>
                    </td>
                    <td data-label="Buyer">{d.counterparty_name ?? "—"}</td>
                    <td data-label="Total" className="r num">
                      {formatRupees(d.doc_total)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="pager">
            <span />
            <Link to={`/b/${businessId}/documents`}>All issued invoices</Link>
          </div>
        </>
      ),
    });
    tabs.push({
      label: <>Drafts {count(draftRows.length, drafts.data?.has_more)}</>,
      panel: (
        <>
          {drafts.error && <p className="hint pad">{errorText(drafts.error)}</p>}
          {drafts.isSuccess && draftRows.length === 0 && <p className="hint pad">No drafts.</p>}
          {draftRows.length > 0 && (
            <table className="products">
              <thead>
                <tr>
                  <th scope="col">Buyer</th>
                  <th scope="col">Date</th>
                  <th scope="col" className="r">
                    Total
                  </th>
                </tr>
              </thead>
              <tbody>
                {draftRows.map((d) => (
                  <tr key={d.id}>
                    <td data-label="Buyer">
                      <Link to={`/b/${businessId}/invoices/${d.id}`}>{buyerOf(d)}</Link>
                    </td>
                    <td data-label="Date" className="num">
                      {d.doc_date ? formatDate(d.doc_date) : "—"}
                    </td>
                    <td data-label="Total" className="r num">
                      {d.total ? formatRupees(d.total) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="pager">
            <span />
            <Link to={`/b/${businessId}/drafts`}>All drafts</Link>
          </div>
        </>
      ),
    });
  }

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page page-wide home">
        <p className="eyebrow">{new Date(`${today}T00:00:00Z`).toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: "UTC" })}</p>
        <h1>
          {greeting(data?.greeting_name)}. <span className="muted">Here is where your business stands today.</span>
        </h1>
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
        {home.isPending && <Loading query={home} />}
        {home.error && (
          <Banner tone="error">
            {errorText(home.error)}{" "}
            <Button type="button" variant="link" onClick={() => home.refetch()}>
              Try again
            </Button>
          </Banner>
        )}
        {data && step && (
          <div className="homegrid">
            <NextStepCard step={step} />
            <div>
              {filing && <Timeline today={today} rows={returns.data?.returns.filter((r) => r.status === "open" || r.status === "unlocked") ?? []} period={gstr1?.period_label} frequency={returns.data?.filing_frequency} />}
              <div className="panel">
                <Tabs tabs={tabs} current={tab} onChange={setTab} label="Home" />
              </div>
            </div>
          </div>
        )}
      </main>
    </>
  );
}
