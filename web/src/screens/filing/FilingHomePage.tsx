import { Link, useParams } from "react-router-dom";

import { errorText } from "../../api/errors";
import { formatDate, previousFy } from "../../format/dates";
import { canPrepareReturns, canViewReturns, canViewUploads } from "../../auth/roles";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { Banner } from "../../kit/Banner";
import { NotFound } from "../../kit/NotFound";
import { TopBar } from "../../kit/TopBar";
import { useChannels } from "../uploads/useChannels";
import { useReturns, type ReturnRow } from "./returns";
import { NoAccess } from "../../kit/NoAccess";

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
        {formatDate(row.due_date)} <span className="chip chip-info">Confirmed on GST portal</span>
      </>
    );
  }
  return (
    <>
      <span className="hint">{row.due_date ? "Check on the GST portal" : "No date available. Check on the GST portal."}</span>
      {row.due_date_source_url && /^https:\/\//.test(row.due_date_source_url) && (
        <div className="hint">
          <a href={row.due_date_source_url} target="_blank" rel="noreferrer noopener">
            Where this date comes from
          </a>
        </div>
      )}
    </>
  );
}

/**
 * /b/:id/filing (R1-M2). The periods, due dates and statuses are the server's; this screen
 * keeps its order, shows the GSTR-1 and GSTR-3B rows only, and offers no filing action yet
 * (the upload screens come in R1-M3).
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

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page page-wide">
        <p className="step">
          <Link to={`/b/${businessId}/home`}>Home</Link>
        </p>
        <h1>Your GST filing</h1>
        {frequency && <p className="hint">{frequency === "quarterly" ? "Quarterly (QRMP)" : "Monthly"} filer.</p>}
        <Banner>We prepare your files and a step-by-step guide. You file on the GST portal yourself.</Banner>
        {now.isPending && business && <p aria-busy="true">Loading…</p>}
        {notSet && (
          <section className="card">
            <p>You haven't chosen how often you file yet.</p>
            <p>
              <Link to={`/b/${businessId}/settings`}>Choose your filing frequency</Link>
            </p>
          </section>
        )}
        {now.isError && <Banner tone="error">We couldn't load your deadlines. {errorText(now.error)}</Banner>}
        {now.isSuccess && !notSet && (
          <section className="card" aria-labelledby="deadlines">
            <h2 id="deadlines">Deadlines</h2>
            {rows.length === 0 ? (
              <p>No returns to show yet.</p>
            ) : (
              <table className="products deadlines">
                <thead>
                  <tr>
                    <th scope="col">Period</th>
                    <th scope="col">Return</th>
                    <th scope="col">Due date</th>
                    <th scope="col">Status</th>
                    {canPrepareReturns(business.role) && <th scope="col">Action</th>}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.instance_id}>
                      <td>
                        <b>{r.period_label}</b>
                        <div className="hint">
                          {formatDate(r.period_start)} to {formatDate(r.period_end)}
                        </div>
                      </td>
                      <td>{FORMS[r.form]}</td>
                      <td>
                        <DueDate row={r} />
                      </td>
                      <td>
                        <span className={`chip ${TONE[r.status] ?? ""}`.trim()}>{STATUS[r.status] ?? r.status}</span>
                      </td>
                      {canPrepareReturns(business.role) && (
                        <td>
                          {r.form === "GSTR1" && (
                            <Link className="btn btn-secondary" to={`/b/${businessId}/filing/${r.instance_id}`}>
                              Review the draft
                            </Link>
                          )}
                          {r.form === "GSTR3B" && (
                            <Link className="btn btn-secondary" to={`/b/${businessId}/filing/${r.instance_id}/worksheet`}>
                              Open the worksheet
                            </Link>
                          )}
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <p>
              <Link to={`/b/${businessId}/settings`}>Change how often you file</Link>
            </p>
          </section>
        )}
        {now.isSuccess && !notSet && business.role !== "support" && (
          <section className="card" aria-labelledby="add">
            <h2 id="add">What you can add</h2>
            <div className="grid2">
              <div>
                <div className="label">Platforms</div>
                <p>
                  {channels.data
                    ? PLATFORMS.filter(([k]) => channels.data[k as "amazon" | "flipkart" | "meesho"]).map(([, n]) => n).join(", ") || "None chosen yet"
                    : channels.isError
                      ? "We couldn't load this."
                      : "…"}
                </p>
              </div>
              <div>
                <div className="label">Own sales invoices</div>
                <p>{channels.data ? (channels.data.own_invoices ? "PDF and/or Excel" : "Not chosen") : "…"}</p>
              </div>
            </div>
            {canViewUploads(business.role) && (
              <div className="row">
                <Link className="btn btn-primary" to={`/b/${businessId}/uploads`}>
                  Continue to uploads
                </Link>
              </div>
            )}
          </section>
        )}
      </main>
    </>
  );
}
