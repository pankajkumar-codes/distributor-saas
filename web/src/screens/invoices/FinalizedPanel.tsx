import { useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { errorText } from "../../api/errors";
import { formatDate } from "../../format/dates";
import { formatRupees } from "../../format/money";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { useSingleFlight } from "../../kit/singleFlight";
import { useDocumentPdfRequest, type DocumentDetail } from "./useFinalize";

const nonzero = (amount: string) => /[1-9]/.test(amount);
const lines = (parts: string[]) => (parts.length ? parts.join(", ") : "—");

const Kv = ({ k, children, total }: { k: ReactNode; children: ReactNode; total?: boolean }) => (
  <div className={total ? "kv total" : "kv"}>
    <span>{k}</span>
    <span className="num">{children}</span>
  </div>
);

/**
 * A finalized invoice in the Ledger look (mocks v16, R.doc): the number in the heading, Parties on the left, Items and
 * Totals on the right, and the PDF as the one primary button. While live numbering is off every invoice is a practice
 * one, and says so here and on the PDF. Every figure is the server's string and the PDF state is the server's; nothing
 * is worked out in the page.
 */
export function FinalizedPanel({ businessId, doc }: { businessId: string; doc: DocumentDetail }) {
  const queryClient = useQueryClient();
  const ask = useDocumentPdfRequest(businessId, doc.id, () => queryClient.invalidateQueries({ queryKey: ["b", businessId, "document", doc.id] }));
  const once = useSingleFlight();
  const s = doc.pdf.status;
  const working = ask.isPending || s === "queued" || s === "rendering";
  return (
    <>
      <p className="eyebrow">
        <Link to={`/b/${businessId}/documents`}>Sell / Issued invoices</Link> / <span className="num">{doc.doc_number}</span>
      </p>
      <div className="between docact">
        <h1>
          Invoice issued <span className="muted num">{doc.doc_number}</span>
        </h1>
        <div className="row">
          <Link to={`/b/${businessId}/documents`}>Issued invoices</Link>
          <Link className="btn btn-secondary" to={`/b/${businessId}/invoices/new`}>
            New invoice
          </Link>
          <Button type="button" variant="primary" busy={working} onClick={() => once((done) => ask.mutate(undefined, { onSettled: done }))}>
            {doc.is_practice ? "Download practice PDF" : "Download PDF"}
          </Button>
        </div>
      </div>
      {ask.error && <Banner tone="error">{errorText(ask.error)}</Banner>}
      {s === "failed" && <Banner tone="error">We couldn't make the PDF. Try again. Your invoice is saved.</Banner>}
      {s === "ready" && doc.pdf.url && (
        <p className="hint">
          <a href={doc.pdf.url} target="_blank" rel="noopener noreferrer">
            Open the PDF
          </a>{" "}
          The link works for a minute; ask again for a new one.
        </p>
      )}
      {doc.is_practice ? (
        <Banner tone="warn">
          <strong>Practice invoice.</strong> Not for customers: it is not a tax invoice and is not in any GST return. Live invoice numbers start once your CA confirms the
          numbering. Issued, locked · {formatDate(doc.doc_date)}
        </Banner>
      ) : (
        <p className="hint">Issued, locked · {formatDate(doc.doc_date)}</p>
      )}
      <div className="grid2 docgrid">
        <section className="panel" aria-labelledby="parties">
          <div className="panel-h">
            <h2 id="parties">Parties</h2>
          </div>
          <div className="pad">
            <div className="kv">
              <span>Buyer</span>
              <span className="r">
                <b>{doc.buyer?.name ?? doc.counterparty_name ?? "Cash sale"}</b>
                {doc.buyer?.gstin && (
                  <>
                    <br />
                    <span className="num sub2">GSTIN {doc.buyer.gstin}</span>
                  </>
                )}
                {doc.buyer && doc.buyer.address.length > 0 && (
                  <>
                    <br />
                    <span className="sub2">{lines(doc.buyer.address)}</span>
                  </>
                )}
              </span>
            </div>
            {doc.ship_to && (
              <div className="kv">
                <span>Ship to</span>
                <span className="r">{[...doc.ship_to.address, doc.ship_to.state].filter(Boolean).join(", ") || "—"}</span>
              </div>
            )}
            <div className="kv">
              <span>Place of supply</span>
              <span className="r">
                <b>{doc.place_of_supply ?? "—"}</b> · {doc.is_inter_state ? "Inter-state (IGST)" : "Within the state (CGST + SGST)"}
                <br />
                <span className="sub2 why">{posBasisText(doc.pos_basis, doc.pos_override_reason)}</span>
              </span>
            </div>
            <Kv k="Seller GSTIN">{doc.gstin}</Kv>
            {doc.due_date && <Kv k="Due date">{formatDate(doc.due_date)}</Kv>}
          </div>
        </section>
        <div>
          <section className="panel" aria-labelledby="items">
            <div className="panel-h">
              <h2 id="items">Items</h2>
            </div>
            <div className="tablewrap">
              <table className="products">
                <thead>
                  <tr>
                    <th scope="col">Item</th>
                    <th scope="col" className="r">Qty</th>
                    <th scope="col" className="r">Rate</th>
                    <th scope="col" className="r">Taxable</th>
                    <th scope="col" className="r">Tax</th>
                    <th scope="col" className="r">Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {doc.lines.map((l) => (
                    <tr key={l.no}>
                      <td data-label="Item">
                        {l.description}
                        <div className="sub2 num">HSN {l.hsn}</div>
                      </td>
                      <td data-label="Qty" className="r num">
                        {l.quantity} {l.uqc}
                      </td>
                      <td data-label="Rate" className="r num">{l.unit_price ? formatRupees(l.unit_price) : "—"}</td>
                      <td data-label="Taxable" className="r num">
                        {formatRupees(l.taxable)}
                        {l.discount && <div className="sub2">after discount {formatRupees(l.discount)}</div>}
                      </td>
                      <td data-label="Tax" className="r num">
                        {l.taxes.length === 0 ? "—" : l.taxes.map((t) => <span key={t.component} className="taxpart">{t.component} {t.rate}% {formatRupees(t.amount)}</span>)}
                      </td>
                      <td data-label="Amount" className="r num">{formatRupees(l.total)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
          <section className="panel" aria-labelledby="totals">
            <div className="panel-h">
              <h2 id="totals">Totals</h2>
            </div>
            <div className="pad">
              {nonzero(doc.line_discount_total) && <Kv k="Line discounts">{formatRupees(doc.line_discount_total)}</Kv>}
              {nonzero(doc.invoice_discount) && <Kv k="Invoice discount">{formatRupees(doc.invoice_discount)}</Kv>}
              {nonzero(doc.charges_total) && <Kv k={doc.charges_label ?? "Charges"}>{formatRupees(doc.charges_total)}</Kv>}
              <Kv k="Taxable value">{formatRupees(doc.taxable_total)}</Kv>
              {doc.is_inter_state ? (
                <Kv k="IGST">{formatRupees(doc.igst_total)}</Kv>
              ) : (
                <>
                  <Kv k="CGST">{formatRupees(doc.cgst_total)}</Kv>
                  <Kv k={doc.utgst ? "UTGST" : "SGST"}>{formatRupees(doc.sgst_total)}</Kv>
                </>
              )}
              {nonzero(doc.cess_total) && <Kv k="Cess">{formatRupees(doc.cess_total)}</Kv>}
              {nonzero(doc.round_off) && <Kv k="Round off">{formatRupees(doc.round_off)}</Kv>}
              <Kv k="Total" total>
                {formatRupees(doc.doc_total)}
              </Kv>
              <p className="hint words">{doc.amount_in_words}</p>
            </div>
          </section>
        </div>
      </div>
    </>
  );
}

/** Why the place of supply is what it is, in the words of the box that was set on the draft. States what the app did; no rule of its own. */
function posBasisText(basis: DocumentDetail["pos_basis"], reason: string | null): string {
  switch (basis) {
    case "override":
      return `Chosen by hand on the draft. Reason given: ${reason ?? "—"}`;
    case "third_party":
      return "The buyer's GSTIN state: the goods went to another person on the buyer's direction (\"Goods go to a third party, not the buyer\" was ticked).";
    case "customer_collects":
      return "The buyer's GSTIN state: the buyer collects the goods (\"The customer collects the goods\" was ticked). CA to confirm.";
    case "buyer_address":
      return "The buyer has no GSTIN: their delivery address, or billing address if none.";
    default:
      return "Where the goods are delivered.";
  }
}
