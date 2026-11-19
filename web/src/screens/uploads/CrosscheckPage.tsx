import { Link, useParams } from "react-router-dom";

import { errorText } from "../../api/errors";
import { canViewUploads } from "../../auth/roles";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { formatDate } from "../../format/dates";
import { formatRupees } from "../../format/money";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { NotFound } from "../../kit/NotFound";
import { TopBar } from "../../kit/TopBar";
import { useCrosscheck } from "./useCrosscheck";
import { NoAccess } from "../../kit/NoAccess";
import { Loading } from "../../kit/Loading";

const FIELD: Record<string, string> = {
  doc_date: "Invoice date",
  buyer_gstin: "Buyer GSTIN",
  place_of_supply: "Place of supply",
  invoice_total: "Invoice total",
  taxable_value: "Taxable value",
  igst: "IGST",
  cgst: "CGST",
  sgst: "SGST/UTGST",
  cess: "Cess",
  lines: "Number of lines",
};
const MONEY = new Set(["invoice_total", "taxable_value", "igst", "cgst", "sgst", "cess"]);

/** The server's value as sent; amounts and dates are only laid out, never worked out here. */
const show = (field: string, value: string) => (MONEY.has(field) ? formatRupees(value) : field === "doc_date" && /^\d{4}-\d{2}-\d{2}$/.test(value) ? formatDate(value) : value);

const docName = (d: { doc_number: string }) => d.doc_number;

/**
 * Own invoices: the Excel sheet against the invoice PDFs (R1-M6 slice 3, D-059; mock v13 screen 4). Read-only: the
 * server lists every difference and never says which side is right, so there are no "use this one" buttons. To change
 * a value, fix the file and upload it again.
 */
export function CrosscheckPage() {
  const { businessId = "" } = useParams();
  const businesses = useMyBusinesses();
  const business = businesses.data?.find((b) => b.business_id === businessId);
  const allowed = Boolean(business && canViewUploads(business.role));
  const check = useCrosscheck(businessId, allowed);

  if (businesses.isPending) {
    return (
      <main className="page" aria-busy="true">
        <p>Loading…</p>
      </main>
    );
  }
  if (!business) return <NotFound />;
  if (!allowed) return <NoAccess businessId={businessId} />;
  const d = check.data;
  const open = d ? d.mismatches.length + d.only_in_excel.length + d.only_in_pdf.length : 0;

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page page-wide">
        <p className="step">
          <Link to={`/b/${businessId}/uploads`}>Upload your reports</Link>
        </p>
        <h1>{d && d.compared && open > 0 ? "PDF and Excel don't match everywhere" : "Cross-check"}</h1>
        {check.isPending && <Loading query={check} />}
        {check.error && (
          <Banner tone="error">
            We couldn't run the cross-check. {errorText(check.error)}{" "}
            <Button type="button" variant="link" onClick={() => check.refetch()}>
              Try again
            </Button>
          </Banner>
        )}
        {d && !d.compared && (
          <section className="card">
            <p>The cross-check runs when you have uploaded both your invoice PDFs and your Excel sheet.</p>
            {d.show_validate_note && <p className="hint">Upload your invoices as PDFs and we can validate your Excel sheet against them.</p>}
          </section>
        )}
        {d && d.compared && (
          <>
            <p className="hint">
              We compared your Excel sheet ({d.excel.documents} invoices) with your PDFs ({d.pdf.documents} invoices). {d.matching} match.
              Below is every difference, with the value each side has. We never say which side is right, and nothing is changed here: fix
              the file and upload it again.
            </p>
            <Banner tone={open === 0 ? "info" : "error"}>
              {open === 0 ? "Everything we could compare matches." : `${open} invoice${open === 1 ? "" : "s"} differ or appear on one side only.`}
            </Banner>
            {d.mismatches.length > 0 && (
              <div className="tablewrap">
                <table className="products">
                  <thead>
                    <tr>
                      <th scope="col">Invoice</th>
                      <th scope="col">What differs</th>
                      <th scope="col">PDF says</th>
                      <th scope="col">Excel says</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.mismatches.flatMap((m) =>
                      m.differences.map((x, i) => (
                        <tr key={`${m.document.doc_number}-${m.document.doc_type}-${x.field}`}>
                          <td data-label="Invoice">{i === 0 ? <b className="num">{docName(m.document)}</b> : ""}</td>
                          <td data-label="What differs">{FIELD[x.field] ?? x.field}</td>
                          <td data-label="PDF says">
                            <span className="diff num">{show(x.field, x.pdf)}</span>
                          </td>
                          <td data-label="Excel says">
                            <span className="diff num">{show(x.field, x.excel)}</span>
                          </td>
                        </tr>
                      )),
                    )}
                  </tbody>
                </table>
              </div>
            )}
            {(d.only_in_excel.length > 0 || d.only_in_pdf.length > 0) && (
              <section className="card" aria-labelledby="one-side">
                <h2 id="one-side">On one side only</h2>
                {d.only_in_excel.length > 0 && (
                  <p>
                    In your Excel sheet but not in your PDFs: <span className="num">{d.only_in_excel.map(docName).join(", ")}</span>
                  </p>
                )}
                {d.only_in_pdf.length > 0 && (
                  <p>
                    In your PDFs but not in your Excel sheet: <span className="num">{d.only_in_pdf.map(docName).join(", ")}</span>
                  </p>
                )}
              </section>
            )}
            {d.not_compared.length > 0 && (
              <section className="card" aria-labelledby="not-compared">
                <h2 id="not-compared">Not compared yet</h2>
                <p className="hint">These invoices have rows that still need a decision, so they are left out until you decide.</p>
                <p className="num">{d.not_compared.map((n) => docName(n.document)).join(", ")}</p>
              </section>
            )}
          </>
        )}
        <div className="row">
          <Link className="btn btn-secondary" to={`/b/${businessId}/uploads`}>
            Back to uploads
          </Link>
        </div>
      </main>
    </>
  );
}
