import { Link, useParams, useSearchParams } from "react-router-dom";

import { errorText } from "../../api/errors";
import { canUpload, canViewUploads } from "../../auth/roles";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { NotFound } from "../../kit/NotFound";
import { TopBar } from "../../kit/TopBar";
import { LedgerHead } from "../filing/ledger";
import { sectionsFor } from "./sections";
import { BundleCard } from "./BundleCard";
import { OwnInvoicesCard } from "./OwnInvoicesCard";
import { UploadCard } from "./UploadCard";
import { useChannels } from "./useChannels";
import { useCrosscheck } from "./useCrosscheck";
import { NoAccess } from "../../kit/NoAccess";
import { Loading } from "../../kit/Loading";

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
  const differ = cross.data ? cross.data.mismatches.length + cross.data.only_in_excel.length + cross.data.only_in_pdf.length : 0;
  // The cross-check lives with your own invoices (mocks v16): the validate note, or the result with a link to it.
  const ownNote = hasOwn && cross.data && (
    <>
      {cross.data.show_validate_note && (
        <Banner>
          <b>Upload your invoices as PDFs and we can validate.</b> With your PDF invoices we check every row of your Excel sheet against the invoice itself.
        </Banner>
      )}
      {cross.data.compared && (
        <div className={`issue ${differ > 0 ? "bad" : "ok"}`} role="status">
          <span className="ic" aria-hidden="true">
            {differ > 0 ? "!" : "✓"}
          </span>
          <div className="tx">
            <b>{differ > 0 ? `${differ} invoices differ between your PDFs and your Excel sheet.` : "Your PDFs and your Excel sheet match."}</b>
          </div>
          <Link to={`/b/${businessId}/uploads/crosscheck`}>{differ > 0 ? "Review the differences" : "See the cross-check"}</Link>
        </div>
      )}
    </>
  );

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page page-wide ledger">
        <LedgerHead
          trail={
            <>
              <Link to={`/b/${businessId}/filing`}>GST filing</Link> / Upload your reports
            </>
          }
          title="Upload your reports"
          lead="Every section is optional. Add what you have; you can come back and add more."
        />
        {channels.isPending && <Loading query={channels} />}
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
        <div className="cardgrid flow2">
          {shown.map((s) =>
            s.id === "own_invoices_excel" ? (
              <OwnInvoicesCard key={s.id} businessId={businessId} label={s.label} hint={s.hint} canUpload={canUpload(business.role)} note={ownNote} />
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
        {shown.length > 0 && canUpload(business.role) && <BundleCard businessId={businessId} bundleId={params.get("bundle")} onBundle={(id) => follow("bundle", id)} />}
      </main>
    </>
  );
}
