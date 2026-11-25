import { useInfiniteQuery, useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { formatDate, formatDateTimeIst } from "../../format/dates";
import { Banner } from "../../kit/Banner";
import { ErrorDetail } from "../../kit/ErrorDetail";
import { Button } from "../../kit/Button";
import { Field } from "../../kit/Field";
import { NotFound } from "../../kit/NotFound";
import { SelectField } from "../../kit/SelectField";
import { TopBar } from "../../kit/TopBar";
import { warningText } from "../onboarding/warnings";
import { NoAccess } from "../../kit/NoAccess";
import { Loading } from "../../kit/Loading";
import { Pager } from "../../kit/Pager";
import { SettingsEyebrow } from "./SettingsEyebrow";

const PER = 6;

type Page = components["schemas"]["AuditPageOut"];
type Row = components["schemas"]["AuditRowOut"];
type Kind = NonNullable<components["schemas"]["AuditExportIn"]["kind"]>;
type Members = components["schemas"]["MembersOut"];
type ExportStatus = components["schemas"]["AuditExportOut"];

// audit.view (docs/PERMISSIONS.md); the server answers anyone else 404.
export const AUDIT_VIEWERS = new Set(["owner", "admin"]);
const KINDS: { value: Kind; label: string }[] = [
  { value: "invoices", label: "Invoices" },
  { value: "gst_filing", label: "GST filing" },
  { value: "team_settings", label: "Team & settings" },
  { value: "support", label: "Support" },
];
const POLL_MS = 2000;
/** Today's date in India as YYYY-MM-DD: the latest day the server accepts. */
const todayIst = () => new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date());
/** The period rules (D-065). The date pickers stop a future day, but not a period that is too long or back to front. */
const RANGE_WORDS: Record<string, string> = {
  date_range_too_long: "Choose a period of 31 days or less.",
  date_range_reversed: "The From date must be on or before the To date.",
  date_in_future: "Choose days up to today. Dates that have not come yet can't be shown.",
};
const EXPORT_WORDS: Record<string, string> = {
  narrow_filter: "That's too many entries for one file. Choose a shorter period, a kind or a person, then export again.",
  not_allowed: "You no longer have access to the audit log.",
};

/** The row's link inside this app, only for screens that exist; anything else shows as text. */
export function rowPath(href: string | null | undefined, businessId: string): string | null {
  if (!href) return null;
  const base = `/b/${businessId}/`;
  if (!href.startsWith(base)) return null;
  const rest = href.slice(base.length);
  const id = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
  const known = new RegExp(`^(settings/(company|filing|support)|products/${id}|customers/${id})$`);
  return known.test(rest) ? href : null;
}

const MARKETPLACE: Record<string, string> = { amazon: "Amazon", flipkart: "Flipkart", meesho: "Meesho", own_invoices: "Own sales invoices" };
const ROLE: Record<string, string> = { owner: "Owner", admin: "Admin", billing: "Billing", ca: "CA" };
const BAND: Record<string, string> = { up_to_threshold: "up to the limit for quarterly filing (QRMP)", above_threshold: "above that limit" };
const REGISTRATION: Record<string, string> = { gstin: "Registered with a GSTIN", enrolment: "Registered with an enrolment number" };
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;

const words = (key: string) => {
  const t = key.replace(/_/g, " ");
  return t.charAt(0).toUpperCase() + t.slice(1);
};
const plainValue = (v: unknown): string => {
  if (Array.isArray(v)) return v.map(plainValue).join(", ");
  if (typeof v === "string" && ISO_DAY.test(v)) return formatDate(v);
  if (typeof v === "string") return v;
  return typeof v === "object" ? "" : String(v);
};

/**
 * "Reason or detail": the reason, then what the entry recorded in plain words. The stored details are the data
 * (ids, codes, lists); a reader, the owner or the CA, gets "Monthly filing from 01-Oct-2026", not
 * `effective_from: 2026-10-01; frequency: monthly; warnings: ["outside_window"]`. Ids and counters stay out of view.
 */
export function detailText(row: Pick<Row, "reason" | "details">): string {
  const parts = row.reason ? [row.reason] : [];
  const d: Record<string, unknown> = Object.fromEntries(Object.entries(row.details ?? {}).filter(([, v]) => v !== null && v !== undefined));
  const take = (k: string) => {
    const v = d[k];
    delete d[k];
    return v;
  };
  // Pairs that read as one sentence.
  if ("frequency" in d && "effective_from" in d) {
    const f = String(take("frequency"));
    const from = String(take("effective_from"));
    parts.push(`${f === "monthly" ? "Monthly" : f === "quarterly" ? "Quarterly (QRMP)" : words(f)} filing from ${plainValue(from)}`);
  }
  if ("rate" in d) {
    const rate = String(take("rate"));
    const from = take("valid_from");
    parts.push(`GST rate ${rate}%${from ? ` from ${plainValue(from)}` : ""}`);
  }
  if ("from" in d && "to" in d) {
    const [a, b] = [String(take("from")), String(take("to"))];
    parts.push(`From ${ROLE[a] ?? words(a)} to ${ROLE[b] ?? words(b)}`);
  }
  if ("fy" in d && "band" in d) {
    const [fy, band] = [String(take("fy")), String(take("band"))];
    parts.push(`Turnover for FY ${fy}: ${BAND[band] ?? words(band)}`);
  }
  if (Array.isArray(d.enabled)) parts.push(`Marketplaces: ${(take("enabled") as unknown[]).map((m) => MARKETPLACE[String(m)] ?? words(String(m))).join(", ")}`);
  if ("registration_kind" in d) parts.push(REGISTRATION[String(take("registration_kind"))] ?? "");
  if (Array.isArray(d.warnings)) {
    const w = (take("warnings") as string[]).map(warningText).join(" ");
    if (w) parts.push(w);
  }
  if (Array.isArray(d.fields)) {
    const f = (take("fields") as unknown[]).map((x) => String(x).replace(/_/g, " ")).join(", ");
    if (f) parts.push(`Changed: ${f}`);
  }
  if ("role" in d) {
    const r = String(take("role"));
    parts.push(`Role: ${ROLE[r] ?? words(r)}`);
  }
  if ("code" in d) parts.push(`Code ${String(take("code"))}`);
  // Anything else by its name, unless it is an id or an internal counter.
  for (const [k, v] of Object.entries(d).sort(([a], [b]) => a.localeCompare(b))) {
    if (k === "seq" || k === "previous_seq" || k.endsWith("_id") || k === "id") continue;
    if (typeof v === "string" && UUID.test(v)) continue;
    const t = plainValue(v);
    if (t) parts.push(`${words(k)}: ${t}`);
  }
  return parts.filter(Boolean).join("; ");
}

/**
 * Settings › Audit log (LLD-2 §7, mocks v9 [D]). Insert-only: nothing here edits or deletes.
 * Filters are the server's (period, person, kind); "Load more" follows its cursor; Export
 * CSV queues a file of what the filters show and polls until it is ready.
 */
export function AuditPage() {
  const { businessId = "" } = useParams();
  const businesses = useMyBusinesses();
  const business = businesses.data?.find((b) => b.business_id === businessId);
  const canView = Boolean(business && AUDIT_VIEWERS.has(business.role));
  // A link may open the log already narrowed to one kind (?kind=support); anything else is ignored.
  const asked = useSearchParams()[0].get("kind") ?? "";
  const [kind, setKind] = useState(KINDS.some((k) => k.value === asked) ? asked : "");
  const [actor, setActor] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [page, setPage] = useState(0);
  const today = todayIst();
  // A new filter starts again at the first page.
  useEffect(() => setPage(0), [kind, actor, from, to]);
  const filters = { kind: (kind || undefined) as Kind | undefined, actor: actor || undefined, from: from || undefined, to: to || undefined };

  const list = useInfiniteQuery<Page, ApiError>({
    queryKey: ["b", businessId, "audit-log", filters],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      call(() =>
        api.GET("/api/v1/b/{business_id}/audit-log", {
          params: { path: { business_id: businessId }, query: { ...filters, cursor: pageParam as string | undefined } },
        }),
      ),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    enabled: canView,
  });
  // The Team tab's list (same key), for the person filter.
  const members = useQuery<Members, ApiError>({
    queryKey: ["b", businessId, "members"],
    queryFn: () =>
      call(() => api.GET("/api/v1/b/{business_id}/members", { params: { path: { business_id: businessId }, query: { limit: 200 } } })),
    enabled: canView,
  });

  const [jobId, setJobId] = useState<string | null>(null);
  const start = useMutation<{ job_id: string }, ApiError>({
    mutationFn: () =>
      call(() =>
        api.POST("/api/v1/b/{business_id}/audit-log/exports", {
          params: { path: { business_id: businessId }, header: { "idempotency-key": crypto.randomUUID() } },
          body: filters,
        }),
      ),
    onSuccess: (r) => setJobId(r.job_id),
  });
  const exported = useQuery<ExportStatus, ApiError>({
    queryKey: ["b", businessId, "audit-export", jobId],
    queryFn: () =>
      call(() =>
        api.GET("/api/v1/b/{business_id}/audit-log/exports/{job_id}", {
          params: { path: { business_id: businessId, job_id: jobId ?? "" } },
        }),
      ),
    enabled: Boolean(jobId),
    refetchInterval: (q) => (q.state.data?.status === "preparing" ? POLL_MS : false),
  });

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
        <Banner tone="error">{errorText(businesses.error)}<ErrorDetail error={businesses.error} /></Banner>
      </main>
    );
  }
  if (!business) return <NotFound />;
  if (!canView) return <NoAccess businessId={businessId} />;
  if (list.error?.status === 404) return <NotFound />;

  const all = list.data?.pages.flatMap((p) => p.items) ?? [];
  // One screen at a time (mocks v16): PER rows per page; Next asks the server for more when the loaded rows run out.
  const lastPage = Math.max(0, Math.ceil(all.length / PER) - 1);
  const at = Math.min(page, lastPage);
  const rows = all.slice(at * PER, at * PER + PER);
  const more = all.length > (at + 1) * PER || Boolean(list.hasNextPage);
  const toPage = (n: number) => {
    if (n > at && all.length <= n * PER && list.hasNextPage) void list.fetchNextPage().then(() => setPage(n));
    else setPage(n);
  };
  const people = (members.data?.members ?? []).map((m) => ({ value: m.user_id, label: m.name || m.email || "Former member" }));
  const narrowed = Boolean(kind || actor || from || to);
  const exportState = exported.data;
  const exportAgain = () => {
    setJobId(null);
    start.mutate();
  };

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page page-wide">
        <SettingsEyebrow businessId={businessId} here="Audit log" />
        <h1>Audit log</h1>
        <p className="lead">Everything that changed in this business, newest first. Entries can't be edited or deleted.</p>

        <div className="audit-bar">
          <div className="filters" role="group" aria-label="Filters">
          <SelectField label="Kind" placeholder="All kinds" options={KINDS} value={kind} onChange={(e) => setKind(e.target.value)} />
          <SelectField label="Person" placeholder="Everyone" options={people} value={actor} onChange={(e) => setActor(e.target.value)} />
          <Field label="From" type="date" max={to || today} value={from} onChange={(e) => setFrom(e.target.value)} />
          <Field
            label="To"
            type="date"
            min={from || undefined}
            max={today}
            value={to}
            onChange={(e) => setTo(e.target.value)}
            hint="Up to 31 days, none in the future. Leave both empty for the last 7 days."
          />
        </div>

        <div className="actions">
          <Button type="button" busy={start.isPending || exportState?.status === "preparing"} onClick={exportAgain}>
            Export CSV
          </Button>
          {exportState?.status === "preparing" && <span role="status"> Preparing your file…</span>}
          {exportState?.status === "ready" && exportState.url && (
            <span role="status">
              {" "}
              Your file is ready ({exportState.rows} {exportState.rows === 1 ? "entry" : "entries"}):{" "}
              <a href={exportState.url} download>
                Download the CSV
              </a>
              . The link works for a minute. This export is in your audit log.
            </span>
          )}
          </div>
        </div>
        {exportState?.status === "expired" && (
          <Banner>That file isn't available any more. Export again to get a fresh one.</Banner>
        )}
        {exportState?.status === "failed" && (
          <Banner tone="error">
            {EXPORT_WORDS[exportState.error_code ?? ""] ?? "We couldn't prepare the file. Try exporting again."}
          </Banner>
        )}
        {(start.error ?? exported.error) && (
          <Banner tone="error">{RANGE_WORDS[(start.error ?? exported.error)!.code] ?? errorText((start.error ?? exported.error)!)}</Banner>
        )}

        {list.error && RANGE_WORDS[list.error.code] && <Banner tone="error">{RANGE_WORDS[list.error.code]}</Banner>}
        {list.error && !RANGE_WORDS[list.error.code] && (
          <Banner tone="error">
            {list.error.status === 0 ? errorText(list.error) : list.error.fix || list.error.message || errorText(list.error)}<ErrorDetail error={list.error} />{" "}
            <Button type="button" variant="link" onClick={() => list.refetch()}>
              Try again
            </Button>
          </Banner>
        )}
        {list.isPending && <Loading query={list} />}
        {list.isSuccess && rows.length === 0 && <p>{narrowed ? "No entries match." : "No entries yet."}</p>}

        {rows.length > 0 && (
          <table className="products audit">
            <thead>
              <tr>
                <th scope="col">When</th>
                <th scope="col">Who</th>
                <th scope="col">What happened</th>
                <th scope="col">Reason or detail</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => {
                const path = rowPath(r.target.href, businessId);
                return (
                  <tr key={`${r.at}-${i}`}>
                    <td data-label="When">{formatDateTimeIst(r.at)}</td>
                    <td data-label="Who" title={r.actor.name}>{r.actor.name}</td>
                    <td data-label="What happened">{path ? <Link to={path}>{r.action_label}</Link> : r.action_label}</td>
                    <td data-label="Reason or detail" title={detailText(r) || undefined}>{detailText(r) || "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        {all.length > 0 && (
          <Pager page={at} size={PER} shown={rows.length} hasMore={more} noun="entries" onPage={toPage} />
        )}
      </main>
    </>
  );
}
