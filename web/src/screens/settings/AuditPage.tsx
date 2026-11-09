import { useInfiniteQuery, useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { formatDateTimeIst } from "../../format/dates";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { Field } from "../../kit/Field";
import { NotFound } from "../../kit/NotFound";
import { SelectField } from "../../kit/SelectField";
import { TopBar } from "../../kit/TopBar";

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

/** "Reason or detail": the reason, then each detail as "key: value". */
export function detailText(row: Pick<Row, "reason" | "details">): string {
  const parts = row.reason ? [row.reason] : [];
  for (const [k, v] of Object.entries(row.details ?? {}).sort(([a], [b]) => a.localeCompare(b))) {
    if (v !== null && v !== undefined) parts.push(`${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`);
  }
  return parts.join("; ");
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
  const [kind, setKind] = useState("");
  const [actor, setActor] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
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
        <Banner tone="error">{errorText(businesses.error)}</Banner>
      </main>
    );
  }
  if (!business || !canView || list.error?.status === 404) return <NotFound />;

  const rows = list.data?.pages.flatMap((p) => p.items) ?? [];
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
        <p className="step">
          <Link to={`/b/${businessId}/home`}>Home</Link>
        </p>
        <h1>Audit log</h1>
        <p className="hint">Everything that changed in this business, newest first. Entries can't be edited or deleted.</p>

        <div className="filters" role="group" aria-label="Filters">
          <SelectField label="Kind" placeholder="All kinds" options={KINDS} value={kind} onChange={(e) => setKind(e.target.value)} />
          <SelectField label="Person" placeholder="Everyone" options={people} value={actor} onChange={(e) => setActor(e.target.value)} />
          <Field label="From" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
          <Field label="To" type="date" value={to} onChange={(e) => setTo(e.target.value)} hint="Leave both empty for the last year." />
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
        {exportState?.status === "expired" && (
          <Banner>That file isn't available any more. Export again to get a fresh one.</Banner>
        )}
        {exportState?.status === "failed" && (
          <Banner tone="error">
            {EXPORT_WORDS[exportState.error_code ?? ""] ?? "We couldn't prepare the file. Try exporting again."}
          </Banner>
        )}
        {(start.error ?? exported.error) && <Banner tone="error">{errorText((start.error ?? exported.error)!)}</Banner>}

        {list.error && (
          <Banner tone="error">
            {list.error.fix ?? list.error.message ?? errorText(list.error)}{" "}
            <Button type="button" variant="link" onClick={() => list.refetch()}>
              Try again
            </Button>
          </Banner>
        )}
        {list.isPending && <p aria-busy="true">Loading…</p>}
        {list.isSuccess && rows.length === 0 && <p>{narrowed ? "No entries match." : "No entries yet."}</p>}

        {rows.length > 0 && (
          <table className="products">
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
                    <td data-label="Who">{r.actor.name}</td>
                    <td data-label="What happened">{path ? <Link to={path}>{r.action_label}</Link> : r.action_label}</td>
                    <td data-label="Reason or detail">{detailText(r) || "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        {list.hasNextPage && (
          <Button type="button" busy={list.isFetchingNextPage} onClick={() => list.fetchNextPage()}>
            Load more
          </Button>
        )}
      </main>
    </>
  );
}
