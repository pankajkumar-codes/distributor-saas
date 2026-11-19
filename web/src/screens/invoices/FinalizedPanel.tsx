import { useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { errorText } from "../../api/errors";
import { formatDate } from "../../format/dates";
import { formatRupees } from "../../format/money";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { useSingleFlight } from "../../kit/singleFlight";
import { useDocumentPdfRequest, type DocumentDetail } from "./useFinalize";

/**
 * A finalized invoice: the number, the total as stored, and the PDF. While live numbering is off every invoice is a
 * practice one, and says so here and on the PDF. The PDF state is the server's; nothing is worked out in the page.
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
        Dated {formatDate(doc.doc_date)} · Total <strong>{formatRupees(doc.doc_total)}</strong>
      </p>
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
