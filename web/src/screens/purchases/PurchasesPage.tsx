import { Link, useParams } from "react-router-dom";

import { errorText } from "../../api/errors";
import { canPrepareReturns, canUpload, canViewUploads } from "../../auth/roles";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { Banner } from "../../kit/Banner";
import { NotFound } from "../../kit/NotFound";
import { TopBar } from "../../kit/TopBar";
import { useOpenDrafts, usePurchaseFiles, useSendPurchaseFile } from "./usePurchases";
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
  if (!business || !allowed) return <NotFound />;
  const mayUpload = canUpload(business.role);

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page">
        <h1>Purchase invoices</h1>
        {canPrepareReturns(business.role) && (
          <p>
            <Link to={`/b/${businessId}/period-files`}>Monthly and quarterly files</Link>
          </p>
        )}
        <>
          <p className="hint">
            Upload a supplier's invoice as a PDF, or a clear photo of the paper bill. You check every detail before anything is added to your products and stock.
          </p>
          {mayUpload && (
            <div className="field">
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
              {send.isPending && <p aria-busy="true">Sending…</p>}
              {send.error && <Banner tone="error">{errorText(send.error)}</Banner>}
            </div>
          )}

          <h2>To check</h2>
          {drafts.isPending && <Loading query={drafts} />}
          {drafts.error && <Banner tone="error">{errorText(drafts.error)}</Banner>}
          {drafts.data?.length === 0 && <p className="hint">Nothing waiting. Uploaded invoices appear here once they are read.</p>}
          <ul>
            {drafts.data?.map((d) => (
              <li key={d.id}>
                <Link to={`/b/${businessId}/purchases/${d.id}`}>
                  {d.doc_number ? `Invoice ${d.doc_number}` : "Invoice to type in"} from {d.file_name}
                </Link>
                {d.reader === "none" && <span className="hint"> We couldn't read this one, so you'll type it in.</span>}
              </li>
            ))}
          </ul>

          <h2>Files</h2>
          {files.data?.length === 0 && <p className="hint">No files yet.</p>}
          <ul>
            {files.data?.map((f) => (
              <li key={f.id}>
                {f.file_name}: {f.status === "rejected" ? (f.reject_message ?? "We couldn't read this file.") : f.status === "read" ? "read" : "being read…"}
              </li>
            ))}
          </ul>
        </>
      </main>
    </>
  );
}
