import { Link, Navigate } from "react-router-dom";

import { errorText } from "../../api/errors";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { Banner } from "../../kit/Banner";
import { TopBar } from "../../kit/TopBar";

// The business picker for people in more than one business (S1); M16 replaces it in S2.
export function BusinessesPage() {
  const businesses = useMyBusinesses();
  if (businesses.data?.length === 0) return <Navigate to="/onboarding/business" replace />;
  return (
    <>
      <TopBar />
      <main className="page">
        <h1>Your businesses</h1>
        {businesses.isPending && <p aria-busy="true">Loading…</p>}
        {businesses.error && <Banner tone="error">{errorText(businesses.error)}</Banner>}
        <ul className="list">
          {businesses.data?.map((b) => (
            <li key={b.business_id}>
              <Link to={`/b/${b.business_id}/home`}>{b.display_name}</Link>
              {b.gstin && <span className="hint"> · GSTIN {b.gstin}</span>}
            </li>
          ))}
        </ul>
      </main>
    </>
  );
}
