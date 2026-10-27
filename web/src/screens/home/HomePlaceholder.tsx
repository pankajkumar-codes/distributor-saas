import { useParams } from "react-router-dom";

import { errorText } from "../../api/errors";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { Banner } from "../../kit/Banner";
import { NotFound } from "../../kit/NotFound";
import { TopBar } from "../../kit/TopBar";

// M3 Home comes in a later S1 PR. The business ID in the URL is only a hint: the server
// decides access on every call, and a business not in /me/businesses is the same
// NotFound as one that doesn't exist (LLD-1 §11.2).
export function HomePlaceholder() {
  const { businessId } = useParams();
  const businesses = useMyBusinesses();
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
  const business = businesses.data.find((b) => b.business_id === businessId);
  if (!business) return <NotFound />;
  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page">
        <h1>Home</h1>
        <p>Your setup list and filing dates come here next.</p>
      </main>
    </>
  );
}
