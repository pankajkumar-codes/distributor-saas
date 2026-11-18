import { Link } from "react-router-dom";

import { errorText } from "../../api/errors";
import { formatDate } from "../../format/dates";
import { formatRupees } from "../../format/money";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { useDocumentPdf, type Document } from "./useFinalize";

/**
 * What shows once a draft is finalized: the number, the total as stored, and the PDF. While live numbering is
 * off every invoice is a practice one, and says so here and on the PDF. Nothing here is worked out in the page.
 */
export function FinalizedPanel({ businessId, doc }: { businessId: string; doc: Document }) {
  const { start, status } = useDocumentPdf(businessId, doc.id);
  const s = status.data?.status;
  const working = start.isPending || (Boolean(start.data) && !status.isError && (s === undefined || s === "queued" || s === "rendering"));
  const failed = s === "failed" || status.isError;
  return (
    <section aria-labelledby="done">
      <h2 id="done">Invoice {doc.doc_number}</h2>
      {doc.is_practice && (
        <Banner tone="info">
          <strong>Practice invoice.</strong> It is not a tax invoice and is not in any GST return. Live invoice numbers start once your CA confirms the numbering.
        </Banner>
      )}
      <p>
        Dated {formatDate(doc.doc_date)} · Total <strong>{formatRupees(doc.doc_total)}</strong>
      </p>
      <Button type="button" busy={working} onClick={() => start.mutate()}>
        {doc.is_practice ? "Download practice PDF" : "Download PDF"}
      </Button>
      {start.error && <Banner tone="error">{errorText(start.error)}</Banner>}
      {failed && <Banner tone="error">We couldn't make the PDF. Try again. Your invoice is saved.</Banner>}
      {s === "ready" && status.data?.url && (
        <p>
          <a href={status.data.url} target="_blank" rel="noopener noreferrer">
            Open the PDF
          </a>{" "}
          <span className="hint">The link works for a minute; ask again for a new one.</span>
        </p>
      )}
      <p>
        <Link to={`/b/${businessId}/invoices/new`}>New invoice</Link> · <Link to={`/b/${businessId}/stock`}>Stock</Link> · <Link to={`/b/${businessId}/home`}>Home</Link>
      </p>
    </section>
  );
}
