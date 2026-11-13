import { Link, useParams, useSearchParams } from "react-router-dom";

import { errorText } from "../../api/errors";
import { canUpload, canViewUploads } from "../../auth/roles";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { Banner } from "../../kit/Banner";
import { NotFound } from "../../kit/NotFound";
import { TopBar } from "../../kit/TopBar";
import { SECTIONS } from "./sections";
import { UploadCard } from "./UploadCard";

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
  // The server answers anyone without uploads.view (billing, support-less others) with a 404.
  if (!business || !canViewUploads(business.role)) return <NotFound />;

  const follow = (section: string, uploadId: string | null) =>
    setParams((prev) => {
      const out = new URLSearchParams(prev);
      if (uploadId) out.set(section, uploadId);
      else out.delete(section);
      return out;
    });

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page">
        <p className="step">
          <Link to={`/b/${businessId}/filing`}>GST filing</Link>
        </p>
        <h1>Upload your reports</h1>
        <p className="hint">Every section is optional. Add what you have; you can come back and add more.</p>
        {SECTIONS.map((s) => (
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
        ))}
      </main>
    </>
  );
}
