import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { errorText } from "../../api/errors";
import { formatDate, previousFy, todayIst } from "../../format/dates";
import { canPrepareReturns, canViewReturns, canViewUploads } from "../../auth/roles";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { Banner } from "../../kit/Banner";
import { NotFound } from "../../kit/NotFound";
import { TopBar } from "../../kit/TopBar";
import { useChannels } from "../uploads/useChannels";
import { useReturns, type ReturnRow } from "./returns";
import { NoAccess } from "../../kit/NoAccess";
import { Pager } from "../../kit/Pager";
import { useReturnLinks } from "../../kit/useReturnLinks";
import { Code, LedgerHead, Panel } from "./ledger";

const PLATFORMS: [string, string][] = [
  ["amazon", "Amazon"],
  ["flipkart", "Flipkart"],
  ["meesho", "Meesho"],
];

// R1 shows only these two forms (IFF and PMT-06 are not part of R1).
const FORMS: Record<string, string> = { GSTR1: "GSTR-1", GSTR3B: "GSTR-3B" };
const STATUS: Record<string, string> = {
  open: "Not filed",
  filed_locked: "Marked as filed",
  unlocked: "Reopened after filing",
  skipped: "Not required",
};
// Mock v13 tones: green once filed, amber when reopened, grey otherwise. Nothing here is red: past-due state is not a status the server sends.
const TONE: Record<string, string> = { filed_locked: "chip-ok", unlocked: "chip-warn", open: "", skipped: "" };

/**
 * One due date as the server sent it (GF-12: never show a date we can't stand behind). A date
 * the server hasn't confirmed is not shown at all; the row says to check the GST portal, with
 * the source the server cites when it is an https link.
 */
function DueDate({ row }: { row: ReturnRow }) {
  if (row.due_date && row.due_date_confirmed) {
    return (
      <>
        <span className="num">{formatDate(row.due_date)}</span>
        <div className="sub2">Confirmed on GST portal</div>
      </>
    );
  }
  return (
    <>
      <span className="hint">{row.due_date ? "Check on the GST portal" : "No date available. Check on the GST portal."}</span>
      {row.due_date_source_url && /^https:\/\//.test(row.due_date_source_url) && (
        <div className="sub2">
          <a href={row.due_date_source_url} target="_blank" rel="noreferrer noopener">
            Where this date comes from
          </a>
        </div>
      )}
    </>
  );
}

/**
 * Deadlines a page at a time (mocks v16 one-screen rule): two periods a page, so a period's GSTR-1 and GSTR-3B always
 * show together (#410). A period with only one row (a lone open return from last year) takes a slot of its own.
 */
const PAGE = 2;

/** The rows grouped by period, in the server's order. */
function byPeriod(rows: ReturnRow[]): ReturnRow[][] {
  const groups: ReturnRow[][] = [];
  const at = new Map<string, number>();
  for (const r of rows) {
    const key = `${r.period_start}|${r.period_end}`;
    const i = at.get(key);
    if (i === undefined) {
      at.set(key, groups.length);
      groups.push([r]);
    } else groups[i].push(r);
  }
  return groups;
}

/** The page to open on: the one with the next open return whose period has ended or is running now. */
function startPage(groups: ReturnRow[][], today: string): number {
  const open = (r: ReturnRow) => r.status === "open" || r.status === "unlocked";
  const find = (test: (r: ReturnRow) => boolean) => groups.findIndex((g) => g.some(test));
  let i = find((r) => open(r) && r.period_start <= today && r.period_end >= today);
  if (i < 0) i = find((r) => open(r) && r.period_end < today);
  if (i < 0) i = find(open);
  return i < 0 ? 0 : Math.floor(i / PAGE);
}

/**
 * /b/:id/filing (R1-M2; mocks v16 "Your GST filing"). The periods, due dates and statuses are the
 * server's; this screen keeps its order and shows the GSTR-1 and GSTR-3B rows only, a page at a time.
 */
export function FilingHomePage() {
  const { businessId = "" } = useParams();
  const businesses = useMyBusinesses();
  const business = businesses.data?.find((b) => b.business_id === businessId);
  // No `fy`: the server picks the current year, so "today" comes from it alone. Last year's is named from the one it answers with.
  const may = Boolean(business && canViewReturns(business.role)); // the list needs returns.view
  const now = useReturns(businessId, undefined, may);
  const before = useReturns(
    businessId,
    now.data ? previousFy(now.data.fy) : undefined,
    may && now.isSuccess && now.data.filing_frequency !== null,
  );
  const links = useReturnLinks(businessId, may);
  const [page, setPage] = useState<number | null>(null);

  const channels = useChannels(businessId, Boolean(business) && business?.role !== "support");

  if (businesses.isPending) {
    return (
      <main className="page" aria-busy="true">
        <p>Loading…</p>
      </main>
    );
  }
  if (!business) return <NotFound />;
  if (!may) return <NoAccess businessId={businessId} />;

  const notSet = now.isSuccess && now.data.filing_frequency === null; // the server sends an empty list, not an error
  // Last year's rows only while something is still open there (a late March or Q4 return).
  const rows: ReturnRow[] = [
    ...(before.data?.returns.filter((r) => r.status === "open" || r.status === "unlocked") ?? []),
    ...(now.data?.returns ?? []),
  ].filter((r) => r.form in FORMS);
  const frequency = now.data?.filing_frequency;
  const today = todayIst();
  const groups = byPeriod(rows);
  const at = Math.min(page ?? startPage(groups, today), Math.max(0, Math.ceil(groups.length / PAGE) - 1));
  const shownGroups = groups.slice(at * PAGE, at * PAGE + PAGE);
  const shown = shownGroups.flat();
  const prepare = canPrepareReturns(business.role);
  const href = (r: ReturnRow) => (r.form === "GSTR1" ? `/b/${businessId}/filing/${r.instance_id}` : `/b/${businessId}/filing/${r.instance_id}/worksheet`);
  // One blue button on the screen: the GSTR-1 to work on next. Every other row has a plain one.
  const next = (r: ReturnRow) => r.instance_id === links.gstr1Id;

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page page-wide ledger">
        <LedgerHead
          trail={<span>GST filing</span>}
          title="Your GST filing"
          lead="We prepare your files and a step-by-step guide. You file on the GST portal yourself."
          actions={
            !notSet && (
              <Link className="btn btn-secondary" to={`/b/${businessId}/settings`}>
                Change how often you file
              </Link>
            )
          }
        />
        {now.isPending && business && <p aria-busy="true">Loading…</p>}
        {notSet && (
          <Panel title="How often you file">
            <div className="pad">
              <p>You haven't chosen how often you file yet.</p>
              <Link className="btn btn-primary" to={`/b/${businessId}/settings`}>
                Choose your filing frequency
              </Link>
            </div>
          </Panel>
        )}
        {now.isError && <Banner tone="error">We couldn't load your deadlines. {errorText(now.error)}</Banner>}
        {now.isSuccess && !notSet && (
          <Panel title="Deadlines" aside={frequency && <span className="hint">{frequency === "quarterly" ? "Quarterly (QRMP) filer." : "Monthly filer."}</span>}>
            {rows.length === 0 ? (
              <p className="pad">No returns to show yet.</p>
            ) : (
              <>
                <div className="tablewrap">
                  <table className="lt deadlines">
                    <thead>
                      <tr>
                        <th scope="col">Period</th>
                        <th scope="col">Return</th>
                        <th scope="col">Due date</th>
                        <th scope="col">Status</th>
                        {prepare && (
                          <th scope="col" className="r">
                            <span className="visually-hidden">Action</span>
                          </th>
                        )}
                      </tr>
                    </thead>
                    <tbody>
                      {shown.map((r) => {
                        const late = (r.status === "open" || r.status === "unlocked") && r.period_end < today;
                        return (
                          <tr key={r.instance_id}>
                            <td className="nowrap">
                              {r.period_label}
                              {/* A quarter says which months it covers; a month's name says it already. */}
                              {r.period_start.slice(0, 7) !== r.period_end.slice(0, 7) && (
                                <div className="sub2 num">
                                  {formatDate(r.period_start)} to {formatDate(r.period_end)}
                                </div>
                              )}
                            </td>
                            <td className="nowrap">
                              {FORMS[r.form]}
                              <Code>{r.form === "GSTR1" ? "Outward sales" : "Summary and tax"}</Code>
                            </td>
                            <td>
                              <DueDate row={r} />
                            </td>
                            <td>
                              <span className={`chip ${r.status === "open" ? (late ? "chip-warn" : "") : (TONE[r.status] ?? "")}`.trim()}>{STATUS[r.status] ?? r.status}</span>
                              {r.status === "filed_locked" && r.arn && <div className="sub2 num">ARN {r.arn}</div>}
                            </td>
                            {prepare && (
                              <td className="r">
                                <Link className={`btn btn-sm ${next(r) ? "btn-primary" : "btn-secondary"}`} to={href(r)} aria-label={`${r.form === "GSTR1" ? (r.status === "filed_locked" ? "View GSTR-1" : "Open GSTR-1") : "Open the GSTR-3B worksheet"} for ${r.period_label}`}>
                                  {r.form === "GSTR1" ? (r.status === "filed_locked" ? "View" : "Open") : "Worksheet"}
                                </Link>
                              </td>
                            )}
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                {groups.length > PAGE && <Pager page={at} size={PAGE} shown={shownGroups.length} total={groups.length} noun="periods" onPage={setPage} />}
              </>
            )}
          </Panel>
        )}
        {now.isSuccess && !notSet && (
          <div className="grid2">
            {business.role !== "support" && (
              <Panel
                title="What you can add"
                aside={
                  canViewUploads(business.role) && (
                    <Link className="btn btn-secondary btn-sm" to={`/b/${businessId}/uploads`}>
                      Upload your reports
                    </Link>
                  )
                }
              >
                <div className="kv">
                  <span>Platforms</span>
                  <span>
                    {channels.data
                      ? PLATFORMS.filter(([k]) => channels.data[k as "amazon" | "flipkart" | "meesho"]).map(([, n]) => n).join(", ") || "None chosen yet"
                      : channels.isError
                        ? "We couldn't load this."
                        : "…"}
                  </span>
                </div>
                <div className="kv">
                  <span>Own sales invoices</span>
                  <span>{channels.data ? (channels.data.own_invoices ? "PDF and/or Excel" : "Not chosen") : "…"}</span>
                </div>
              </Panel>
            )}
            <Panel title="Due dates">
              <p className="pad hint">Dates come from the national GST calendar. A date extended for your state shows here once it is published. If a date is missing, check on the GST portal.</p>
            </Panel>
          </div>
        )}
      </main>
    </>
  );
}
