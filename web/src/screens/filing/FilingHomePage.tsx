import { Link, useParams } from "react-router-dom";

import { errorText } from "../../api/errors";
import { fyIst, formatDate, previousFy } from "../../format/dates";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { Banner } from "../../kit/Banner";
import { NotFound } from "../../kit/NotFound";
import { TopBar } from "../../kit/TopBar";
import { useReturns, type ReturnRow } from "./returns";

// R1 shows only these two forms (IFF and PMT-06 are not part of R1).
const FORMS: Record<string, string> = { GSTR1: "GSTR-1", GSTR3B: "GSTR-3B" };
const STATUS: Record<string, string> = {
  open: "Not filed",
  filed_locked: "Marked as filed",
  unlocked: "Reopened after filing",
  skipped: "Not required",
};

/** One due date as the server sent it. Nothing here is worked out in the browser. */
function DueDate({ row }: { row: ReturnRow }) {
  if (!row.due_date) return <span className="hint">No date available. Check on the GST portal.</span>;
  return (
    <>
      {formatDate(row.due_date)}
      {!row.due_date_confirmed && (
        <>
          {" "}
          <span className="tag">To be confirmed</span>
          <div className="hint">
            Check on the GST portal.
            {row.due_date_source_url && /^https:\/\//.test(row.due_date_source_url) && (
              <>
                {" "}
                <a href={row.due_date_source_url} target="_blank" rel="noreferrer noopener">
                  Where this date comes from
                </a>
              </>
            )}
          </div>
        </>
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
  const fy = fyIst();
  const last = previousFy(fy);
  const now = useReturns(businessId, fy, Boolean(business));
  const before = useReturns(businessId, last, Boolean(business) && now.isSuccess && now.data.filing_frequency !== null);

  if (businesses.isPending) {
    return (
      <main className="page" aria-busy="true">
        <p>Loading…</p>
      </main>
    );
  }
  if (!business) return <NotFound />;

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
      <main className="page">
        <p className="step">
          <Link to={`/b/${businessId}/home`}>Home</Link>
        </p>
        <h1>Your GST filing</h1>
        {frequency && <p className="hint">{frequency === "quarterly" ? "Quarterly (QRMP)" : "Monthly"} filer.</p>}
        <Banner>We prepare your files and a guide. You file on the GST portal yourself.</Banner>
        {now.isPending && business && <p aria-busy="true">Loading…</p>}
        {notSet && (
          <section className="card">
            <p>You haven't chosen how often you file yet.</p>
            <p>
              <Link to={`/b/${businessId}/settings/filing`}>Choose your filing frequency</Link>
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
              <table className="products">
                <thead>
                  <tr>
                    <th scope="col">Period</th>
                    <th scope="col">Return</th>
                    <th scope="col">Due date</th>
                    <th scope="col">Status</th>
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
                        <span className="chip">{STATUS[r.status] ?? r.status}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <p>
              <Link to={`/b/${businessId}/settings/filing`}>Change how often you file</Link>
            </p>
          </section>
        )}
      </main>
    </>
  );
}
