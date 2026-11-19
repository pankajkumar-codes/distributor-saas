import { Link, useParams, useSearchParams } from "react-router-dom";

import { errorText } from "../../api/errors";
import { canUpload, canViewUploads } from "../../auth/roles";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { NotFound } from "../../kit/NotFound";
import { TopBar } from "../../kit/TopBar";
import { sectionsFor } from "./sections";
import { BundleCard } from "./BundleCard";
import { OwnInvoicesCard } from "./OwnInvoicesCard";
import { UploadCard } from "./UploadCard";
import { useChannels } from "./useChannels";
import { useCrosscheck } from "./useCrosscheck";
import { NoAccess } from "../../kit/NoAccess";

/**
 * Upload your reports (R1-M3, BRD GF-13). Every section is optional. Uploads belong to the
 * business, not to a period: the file's own months decide where its rows go. Which upload each
 * card is following lives in the URL (`?amazon=<id>`), so a reload picks up where it was.
 */
export function UploadsPage() {
  const { businessId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const businesses = useMyBusinesses();
  const business = businesses.data?.find((b) => b.business_id === businessId);
  const channels = useChannels(businessId, Boolean(business && canViewUploads(business.role)));

  const hasOwn = (channels.data?.own_invoices ?? false) && Boolean(business && canViewUploads(business.role));
  const cross = useCrosscheck(businessId, hasOwn);

  if (businesses.isPending) {
    return (
      <main className="page" aria-busy="true">
        <p>Loading…</p>
      </main>
    );
  }
  if (businesses.error) {
    return (
      <main className="page page-wide">
        <Banner tone="error">{errorText(businesses.error)}</Banner>
      </main>
    );
  }
  // The server answers anyone without uploads.view (billing, support-less others) with a 404.
  if (!business) return <NotFound />;
  if (!canViewUploads(business.role)) return <NoAccess businessId={businessId} />;

  const follow = (section: string, uploadId: string | null) =>
    setParams((prev) => {
      const out = new URLSearchParams(prev);
      if (uploadId) out.set(section, uploadId);
      else out.delete(section);
      return out;
    });

  const shown = channels.data ? sectionsFor(channels.data) : [];

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page page-wide">
        <p className="step">
          <Link to={`/b/${businessId}/filing`}>GST filing</Link>
        </p>
        <h1>Upload your reports</h1>
        <p className="hint">Every section is optional. Add what you have; you can come back and add more.</p>
        {channels.isPending && <p aria-busy="true">Loading…</p>}
        {channels.error && (
          <Banner tone="error">
            We couldn't load where you sell. {errorText(channels.error)}{" "}
            <Button type="button" variant="link" onClick={() => channels.refetch()}>
              Try again
            </Button>
          </Banner>
        )}
        {channels.data && shown.length === 0 && (
          <Banner>
            You haven't said where you sell yet. <Link to={`/b/${businessId}/settings`}>Choose it in Business details</Link>, then come back to add your files.
          </Banner>
        )}
        {hasOwn && cross.data && cross.data.show_validate_note && (
          <Banner>
            <b>Upload your invoices as PDFs and we can validate.</b> With your PDF invoices we check every row of your Excel sheet against the invoice itself.
          </Banner>
        )}
        {hasOwn && cross.data && cross.data.compared && (
          <Banner tone={cross.data.mismatches.length + cross.data.only_in_excel.length + cross.data.only_in_pdf.length > 0 ? "error" : "info"}>
            {cross.data.mismatches.length + cross.data.only_in_excel.length + cross.data.only_in_pdf.length > 0 ? (
              <>
                {cross.data.mismatches.length + cross.data.only_in_excel.length + cross.data.only_in_pdf.length} invoices differ between your PDFs and your Excel sheet.{" "}
                <Link to={`/b/${businessId}/uploads/crosscheck`}>Review the differences</Link>
              </>
            ) : (
              <>Your PDFs and your Excel sheet match. <Link to={`/b/${businessId}/uploads/crosscheck`}>See the cross-check</Link></>
            )}
          </Banner>
        )}
        {shown.length > 0 && canUpload(business.role) && <BundleCard businessId={businessId} bundleId={params.get("bundle")} onBundle={(id) => follow("bundle", id)} />}
        <div className="uploads-grid">
        {shown.map((s) =>
          s.id === "own_invoices_excel" ? (
            <div key={s.id} className="span-all">
              <OwnInvoicesCard businessId={businessId} label={s.label} hint={s.hint} canUpload={canUpload(business.role)} />
            </div>
          ) : (
          <UploadCard
            key={s.id}
            businessId={businessId}
            section={s.id}
            label={s.label}
            hint={s.hint}
            canUpload={canUpload(business.role)}
            uploadId={params.get(s.id)}
            onUpload={(id) => follow(s.id, id)}
          />
          ),
        )}
        </div>
      </main>
    </>
  );
}
