import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { errorText } from "../../api/errors";
import { canViewUploads } from "../../auth/roles";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { formatDate } from "../../format/dates";
import { formatRupees } from "../../format/money";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { NotFound } from "../../kit/NotFound";
import { Pager } from "../../kit/Pager";
import { TopBar } from "../../kit/TopBar";
import { LedgerHead, Panel } from "../filing/ledger";
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

const DIFF_PAGE = 6; // difference rows a page, so the screen does not scroll

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
  const [page, setPage] = useState(0);

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

  const lines = d ? d.mismatches.flatMap((m) => m.differences.map((x, i) => ({ m, x, first: i === 0 }))) : [];
  const slice = lines.slice(page * DIFF_PAGE, (page + 1) * DIFF_PAGE);
  const back = (
    <Link className="btn btn-secondary" to={`/b/${businessId}/uploads`}>
      Back to uploads
    </Link>
  );

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page page-wide ledger">
        <LedgerHead
          trail={
            <>
              <Link to={`/b/${businessId}/filing`}>GST filing</Link> / <Link to={`/b/${businessId}/uploads`}>Upload your reports</Link> / Cross-check
            </>
          }
          title="Your PDFs and your Excel sheet"
          lead={
            d && d.compared
              ? open === 0
                ? `All ${d.matching} invoices we could compare match.`
                : `${open} invoice${open === 1 ? "" : "s"} differ or appear on one side only. Fix the Excel sheet or the PDF and upload it again.`
              : undefined
          }
          actions={back}
        />
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
          <section className="panel">
            <div className="pad">
              <p>The cross-check runs when you have uploaded both your invoice PDFs and your Excel sheet.</p>
              {d.show_validate_note && <p className="hint">Upload your invoices as PDFs and we can validate your Excel sheet against them.</p>}
            </div>
          </section>
        )}
        {d && d.compared && (
          <>
            <Panel
              title={open > 0 ? "PDF and Excel don't match everywhere" : "Compared invoice by invoice"}
              aside={<span className={`chip ${open > 0 ? "chip-bad" : "chip-ok"}`}>{open > 0 ? `${open} differ` : `${d.matching} match`}</span>}
            >
              <p className="pad-x hint">
                Your Excel sheet has <span className="num">{d.excel.documents}</span> invoices and your PDFs <span className="num">{d.pdf.documents}</span>;{" "}
                <span className="num">{d.matching}</span> match. Each difference shows the value on each side. We never say which side is right, and nothing is
                changed here.
              </p>
              {lines.length > 0 ? (
                <>
                  <div className="tablewrap">
                    <table className="lt dense">
                      <thead>
                        <tr>
                          <th scope="col">Invoice</th>
                          <th scope="col">What differs</th>
                          <th scope="col" className="r">
                            In PDF
                          </th>
                          <th scope="col" className="r">
                            In Excel
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {slice.map(({ m, x, first }, i) => (
                          <tr key={`${m.document.doc_number}-${m.document.doc_type}-${x.field}`}>
                            <td className="num">{first || i === 0 ? docName(m.document) : ""}</td>
                            <td>{FIELD[x.field] ?? x.field}</td>
                            <td className="r num">
                              <span className="diff">{show(x.field, x.pdf)}</span>
                            </td>
                            <td className="r num">
                              <span className="diff">{show(x.field, x.excel)}</span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {lines.length > DIFF_PAGE && <Pager page={page} size={DIFF_PAGE} shown={slice.length} total={lines.length} noun="differences" onPage={setPage} />}
                </>
              ) : (
                open === 0 && <p className="pad">Everything we could compare matches.</p>
              )}
            </Panel>
            {(d.only_in_excel.length > 0 || d.only_in_pdf.length > 0 || d.not_compared.length > 0) && (
              <div className="grid2">
                {(d.only_in_excel.length > 0 || d.only_in_pdf.length > 0) && (
                  <Panel title="On one side only">
                    {d.only_in_excel.length > 0 && (
                      <div className="kv">
                        <span>In Excel, not in your PDFs</span>
                        <span className="num">{d.only_in_excel.map(docName).join(", ")}</span>
                      </div>
                    )}
                    {d.only_in_pdf.length > 0 && (
                      <div className="kv">
                        <span>In your PDFs, not in Excel</span>
                        <span className="num">{d.only_in_pdf.map(docName).join(", ")}</span>
                      </div>
                    )}
                  </Panel>
                )}
                {d.not_compared.length > 0 && (
                  <Panel title="Not compared yet">
                    <p className="pad-x hint">Left out until their held rows are decided.</p>
                    <p className="pad num">{d.not_compared.map((n) => docName(n.document)).join(", ")}</p>
                  </Panel>
                )}
              </div>
            )}
          </>
        )}
      </main>
    </>
  );
}
