import { useParams } from "react-router-dom";

import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { NotFound } from "../../kit/NotFound";
import { TopBar } from "../../kit/TopBar";
import { SettingsEyebrow } from "./SettingsEyebrow";
import { PlatformsSection } from "./PlatformsSection";

// The server refuses everyone else with a 404 (settings.edit, docs/PERMISSIONS.md); the boxes are off for them.
const EDITORS = new Set(["owner", "admin"]);

/**
 * /b/:id/onboarding/marketplaces: the Home checklist's "Marketplaces you sell on" item. It is the same
 * "Where you sell" section as in Business setup (ON-2), on a page of its own so the checklist has somewhere to go.
 */
export function MarketplacesPage() {
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
  if (!business) return <NotFound />;

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page">
        <SettingsEyebrow businessId={businessId} here="Marketplaces you sell on" />
        <h1>Marketplaces you sell on</h1>
        <p className="lead">This sets which returns and deadlines we show you. You can change it any time in Business setup.</p>
        <PlatformsSection businessId={businessId} canEdit={EDITORS.has(business.role)} />
      </main>
    </>
  );
}
