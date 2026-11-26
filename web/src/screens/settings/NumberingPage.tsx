import { useParams } from "react-router-dom";

import { errorText } from "../../api/errors";
import { SUPPORT_ROLE, useMyBusinesses } from "../../auth/useMyBusinesses";
import { FEATURES } from "../../features";
import { Banner } from "../../kit/Banner";
import { NotFound } from "../../kit/NotFound";
import { TopBar } from "../../kit/TopBar";
import { EDITORS } from "./CompanyPage";
import { NumberingSection } from "./NumberingSection";
import { SettingsEyebrow } from "./SettingsEyebrow";

/** Settings › Invoice numbering (mocks v17, R.numbering; #461): its own page, so Business setup still fits one screen. */
export function NumberingPage() {
  const { businessId = "" } = useParams();
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
      <main className="page page-wide">
        <Banner tone="error">{errorText(businesses.error)}</Banner>
      </main>
    );
  }
  if (!business || business.role === SUPPORT_ROLE || !FEATURES.invoicing) return <NotFound />;
  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page page-wide">
        <SettingsEyebrow businessId={businessId} here="Invoice numbering" />
        <h1>Invoice numbering</h1>
        <NumberingSection businessId={businessId} canEdit={EDITORS.has(business.role)} isOwner={business.role === "owner"} />
      </main>
    </>
  );
}
