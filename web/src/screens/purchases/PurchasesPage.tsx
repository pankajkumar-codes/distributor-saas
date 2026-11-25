import { Link, useParams } from "react-router-dom";

import { errorText } from "../../api/errors";
import { canPrepareReturns, canUpload, canViewUploads } from "../../auth/roles";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { Banner } from "../../kit/Banner";
import { NotFound } from "../../kit/NotFound";
import { TopBar } from "../../kit/TopBar";
import { PageHead } from "../../kit/PageHead";
import { formatDateTimeIst } from "../../format/dates";
import { useOpenDrafts, usePurchaseFiles, useSendPurchaseFile } from "./usePurchases";
import { NoAccess } from "../../kit/NoAccess";
import { Loading } from "../../kit/Loading";

/**
 * Purchase invoices (R2-M2): upload a supplier's invoice (a PDF, or a photo of a paper bill), then check what we read
 * before anything is added to your products.
 */
export function PurchasesPage() {
  const { businessId = "" } = useParams();
  const businesses = useMyBusinesses();
  const business = businesses.data?.find((b) => b.business_id === businessId);
  const allowed = Boolean(business && canViewUploads(business.role));
  const files = usePurchaseFiles(businessId, allowed);
  const drafts = useOpenDrafts(businessId, allowed);
  const send = useSendPurchaseFile(businessId);

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
  if (!business) return <NotFound />;
  if (!allowed) return <NoAccess businessId={businessId} />;
  const mayUpload = canUpload(business.role);

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page page-wide">
        <PageHead crumbs={[{ label: "Sell" }, { label: "Purchase invoices" }]} title="Purchase invoices" sub="Upload a supplier invoice. We read it; you check it before it counts.">
          {canPrepareReturns(business.role) && (
            <Link className="btn btn-secondary" to={`/b/${businessId}/period-files`}>
              Monthly and quarterly files
            </Link>
          )}
        </PageHead>
        {mayUpload && (
          <section className="panel pad" aria-label="Upload">
            <div className="field upload-box">
              <label htmlFor="purchase-file">Choose an invoice (PDF, JPG, PNG or HEIC)</label>
              <input
                id="purchase-file"
                type="file"
                accept=".pdf,.jpg,.jpeg,.png,.heic,application/pdf,image/*"
                disabled={send.isPending}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) send.mutate(file);
                  e.target.value = "";
                }}
              />
              <p className="hint">A PDF, or a clear photo of the paper bill. You check every detail before anything is added to your products and stock.</p>
              {send.isPending && <p aria-busy="true">Sending…</p>}
              {send.error && <Banner tone="error">{errorText(send.error)}</Banner>}
            </div>
          </section>
        )}

        <section className="panel" aria-labelledby="to-check">
          <div className="panel-h">
            <h2 id="to-check">To check</h2>
            {!!drafts.data?.length && <span className="chip chip-warn">{drafts.data.length}</span>}
          </div>
          {drafts.isPending && <Loading query={drafts} />}
          {drafts.error && <Banner tone="error">{errorText(drafts.error)}</Banner>}
          {drafts.data?.length === 0 && <p className="empty">Nothing waiting. Uploaded invoices appear here once they are read.</p>}
          {!!drafts.data?.length && (
            <div className="scrollpanel short" tabIndex={0} role="region" aria-label="Invoices to check">
              <table className="ltable">
                <thead>
                  <tr>
                    <th scope="col">Invoice</th>
                    <th scope="col">Supplier GSTIN</th>
                    <th scope="col">Read</th>
                  </tr>
                </thead>
                <tbody>
                  {drafts.data.map((d) => (
                    <tr key={d.id}>
                      <td>
                        <Link className="pname" to={`/b/${businessId}/purchases/${d.id}`}>
                          {d.doc_number ? `Invoice ${d.doc_number}` : "Invoice to type in"} from {d.file_name}
                        </Link>
                      </td>
                      <td className={d.supplier_gstin ? "num" : undefined}>{d.supplier_gstin ?? "—"}</td>
                      <td>
                        {d.reader === "none" ? (
                          <span className="chip chip-warn">Couldn't read: type it in</span>
                        ) : (
                          <span className="chip chip-ok">Read</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="panel" aria-labelledby="files-h">
          <div className="panel-h">
            <h2 id="files-h">Files</h2>
          </div>
          {files.data?.length === 0 && <p className="empty">No files yet.</p>}
          {!!files.data?.length && (
            <div className="scrollpanel short" tabIndex={0} role="region" aria-label="Uploaded files">
              <table className="ltable">
                <thead>
                  <tr>
                    <th scope="col">File</th>
                    <th scope="col">Uploaded</th>
                    <th scope="col">Result</th>
                  </tr>
                </thead>
                <tbody>
                  {files.data.map((f) => (
                    <tr key={f.id}>
                      <td>{f.file_name}</td>
                      <td className="num">{formatDateTimeIst(f.created_at)}</td>
                      <td>{f.status === "rejected" ? (f.reject_message ?? "We couldn't read this file.") : f.status === "read" ? "Read" : "Being read…"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </main>
    </>
  );
}
