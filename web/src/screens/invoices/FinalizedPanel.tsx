import { useQueryClient } from "@tanstack/react-query";
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

/**
 * A finalized invoice: the number, buyer, every line with its tax split, the totals as stored, and the PDF. While live
 * numbering is off every invoice is a practice one, and says so here and on the PDF. Every figure is the server's string
 * and the PDF state is the server's; nothing is worked out in the page.
 */
export function FinalizedPanel({ businessId, doc }: { businessId: string; doc: DocumentDetail }) {
  const queryClient = useQueryClient();
  const ask = useDocumentPdfRequest(businessId, doc.id, () => queryClient.invalidateQueries({ queryKey: ["b", businessId, "document", doc.id] }));
  const once = useSingleFlight();
  const s = doc.pdf.status;
  const working = ask.isPending || s === "queued" || s === "rendering";
  return (
    <section aria-labelledby="done">
      <h2 id="done">Invoice {doc.doc_number}</h2>
      {doc.is_practice && (
        <Banner tone="info">
          <strong>Practice invoice.</strong> It is not a tax invoice and is not in any GST return. Live invoice numbers start once your CA confirms the numbering.
        </Banner>
      )}
      <p>
        Dated {formatDate(doc.doc_date)} · Total <strong>{formatRupees(doc.doc_total)}</strong> · <span className="chip">Issued, locked</span>
        {doc.is_practice && <span className="chip chip-warn"> Practice · not for customers</span>}
      </p>
      <section aria-labelledby="parties">
        <h3 id="parties">Parties</h3>
        <dl className="facts">
          <dt>Buyer</dt>
          <dd>
            {doc.buyer?.name ?? doc.counterparty_name ?? "Cash sale"}
            {doc.buyer?.gstin && <> · GSTIN {doc.buyer.gstin}</>}
            {doc.buyer && doc.buyer.address.length > 0 && <><br />{lines(doc.buyer.address)}</>}
          </dd>
          {doc.ship_to && (
            <>
              <dt>Ship to</dt>
              <dd>{[...doc.ship_to.address, doc.ship_to.state].filter(Boolean).join(", ") || "—"}</dd>
            </>
          )}
          <dt>Place of supply</dt>
          <dd>{doc.place_of_supply ?? "—"} · {doc.is_inter_state ? "Inter-state (IGST)" : "Within the state (CGST + SGST)"}</dd>
          <dt>Seller GSTIN</dt>
          <dd>{doc.gstin}</dd>
          {doc.due_date && (
            <>
              <dt>Due date</dt>
              <dd>{formatDate(doc.due_date)}</dd>
            </>
          )}
        </dl>
      </section>
      <section aria-labelledby="items">
        <h3 id="items">Items</h3>
        <div className="tablewrap">
          <table className="products">
            <thead>
              <tr>
                <th scope="col">Item</th>
                <th scope="col">Qty</th>
                <th scope="col">Rate</th>
                <th scope="col">Taxable</th>
                <th scope="col">Tax</th>
                <th scope="col">Amount</th>
              </tr>
            </thead>
            <tbody>
              {doc.lines.map((l) => (
                <tr key={l.no}>
                  <td data-label="Item">
                    <strong>{l.description}</strong>
                    <br />
                    <span className="hint">HSN {l.hsn}</span>
                  </td>
                  <td data-label="Qty">
                    {l.quantity} {l.uqc}
                  </td>
                  <td data-label="Rate">{l.unit_price ? formatRupees(l.unit_price) : "—"}</td>
                  <td data-label="Taxable">
                    {formatRupees(l.taxable)}
                    {l.discount && <><br /><span className="hint">after discount {formatRupees(l.discount)}</span></>}
                  </td>
                  <td data-label="Tax">
                    {l.taxes.length === 0 ? "—" : l.taxes.map((t) => <span key={t.component} className="taxpart">{t.component} {t.rate}% {formatRupees(t.amount)}</span>)}
                  </td>
                  <td data-label="Amount">{formatRupees(l.total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section aria-labelledby="totals">
        <h3 id="totals">Totals</h3>
        <dl className="facts totals">
          {nonzero(doc.line_discount_total) && (<><dt>Line discounts</dt><dd>{formatRupees(doc.line_discount_total)}</dd></>)}
          {nonzero(doc.invoice_discount) && (<><dt>Invoice discount</dt><dd>{formatRupees(doc.invoice_discount)}</dd></>)}
          {nonzero(doc.charges_total) && (<><dt>{doc.charges_label ?? "Charges"}</dt><dd>{formatRupees(doc.charges_total)}</dd></>)}
          <dt>Taxable value</dt>
          <dd>{formatRupees(doc.taxable_total)}</dd>
          {doc.is_inter_state ? (
            <><dt>IGST</dt><dd>{formatRupees(doc.igst_total)}</dd></>
          ) : (
            <>
              <dt>CGST</dt>
              <dd>{formatRupees(doc.cgst_total)}</dd>
              <dt>{doc.utgst ? "UTGST" : "SGST"}</dt>
              <dd>{formatRupees(doc.sgst_total)}</dd>
            </>
          )}
          {nonzero(doc.cess_total) && (<><dt>Cess</dt><dd>{formatRupees(doc.cess_total)}</dd></>)}
          {nonzero(doc.round_off) && (<><dt>Round off</dt><dd>{formatRupees(doc.round_off)}</dd></>)}
          <dt><strong>Total</strong></dt>
          <dd><strong>{formatRupees(doc.doc_total)}</strong></dd>
        </dl>
        <p className="hint">{doc.amount_in_words}</p>
      </section>
      <Button type="button" busy={working} onClick={() => once((done) => ask.mutate(undefined, { onSettled: done }))}>
        {doc.is_practice ? "Download practice PDF" : "Download PDF"}
      </Button>
      {ask.error && <Banner tone="error">{errorText(ask.error)}</Banner>}
      {s === "failed" && <Banner tone="error">We couldn't make the PDF. Try again. Your invoice is saved.</Banner>}
      {s === "ready" && doc.pdf.url && (
        <p>
          <a href={doc.pdf.url} target="_blank" rel="noopener noreferrer">
            Open the PDF
          </a>{" "}
          <span className="hint">The link works for a minute; ask again for a new one.</span>
        </p>
      )}
      <p>
        <Link to={`/b/${businessId}/invoices/new`}>New invoice</Link> · <Link to={`/b/${businessId}/documents`}>Issued invoices</Link> · <Link to={`/b/${businessId}/stock`}>Stock</Link>
      </p>
    </section>
  );
}
