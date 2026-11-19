import { Link, useParams } from "react-router-dom";

import { errorText } from "../../api/errors";
import { canCreateDocuments } from "../../auth/roles";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { Banner } from "../../kit/Banner";
import { NotFound } from "../../kit/NotFound";
import { TopBar } from "../../kit/TopBar";
import { FinalizedPanel } from "./FinalizedPanel";
import { useDocument } from "./useFinalize";
import { Loading } from "../../kit/Loading";

/** One issued invoice, read from the server, so the PDF is there after a reload or on another day. */
export function DocumentPage() {
  const { businessId = "", documentId = "" } = useParams();
  const businesses = useMyBusinesses();
  const business = businesses.data?.find((b) => b.business_id === businessId);
  const doc = useDocument(businessId, documentId);
  if (businesses.isPending) return <main className="page" aria-busy="true"><p>Loading…</p></main>;
  if (!business || !canCreateDocuments(business.role) || doc.error?.status === 404) return <NotFound />;
  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page">
        <p className="step">
          <Link to={`/b/${businessId}/documents`}>Issued invoices</Link>
        </p>
        <h1>Invoice issued</h1>
        {doc.error && <Banner tone="error">{errorText(doc.error)}</Banner>}
        {doc.isPending && <Loading query={doc} />}
        {doc.data && <FinalizedPanel businessId={businessId} doc={doc.data} />}
      </main>
    </>
  );
}
