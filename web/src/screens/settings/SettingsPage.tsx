import { Link, Navigate, useParams } from "react-router-dom";

import { errorText } from "../../api/errors";
import { SUPPORT_ROLE, useMyBusinesses } from "../../auth/useMyBusinesses";
import { Banner } from "../../kit/Banner";
import { NotFound } from "../../kit/NotFound";
import { TopBar } from "../../kit/TopBar";
import { AUDIT_VIEWERS } from "./AuditPage";
import { CompanyPage } from "./CompanyPage";
import { FilingPage } from "./FilingPage";
import { TEAM_MANAGERS } from "../team/TeamPage";
import { SUPPORT_VIEWERS } from "./SupportPage";

/**
 * Business setup at /b/:id/settings (mock v13, screen 9): business details, where you sell and the filing
 * frequency on ONE page. Each part keeps its own server calls and its own Save, because each is checked by the
 * server on its own (versions, change windows), so one part failing never loses another's edits. Access and
 * security links sit below. The old /settings/company and /settings/filing addresses come here.
 */
export function SettingsPage() {
  const { businessId = "" } = useParams();
  const businesses = useMyBusinesses();
  const business = businesses.data?.find((b) => b.business_id === businessId);
  const member = Boolean(business && business.role !== SUPPORT_ROLE);

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
  if (!business) return <NotFound />;

  const base = `/b/${businessId}/settings`;
  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page page-wide">
        <p className="step">
          <Link to={`/b/${businessId}/home`}>Home</Link>
        </p>
        <h1>Business setup</h1>
        <p className="hint">Change how you file or where you sell at any time. Deadlines update straight away.</p>

        {member && (
          <div className="grid2 setup-cols">
            <CompanyPage embedded />
            <FilingPage embedded />
          </div>
        )}

        <nav className="card" aria-labelledby="set-more">
          <h2 id="set-more">Access and security</h2>
          <ul className="list">
            {TEAM_MANAGERS.has(business.role) && (
              <li>
                <Link to={`${base}/team`}>Your team</Link>
              </li>
            )}
            {SUPPORT_VIEWERS.has(business.role) && (
              <li>
                <Link to={`${base}/support`}>Support access</Link>
              </li>
            )}
            {AUDIT_VIEWERS.has(business.role) && (
              <li>
                <Link to={`${base}/audit`}>Audit log</Link>
              </li>
            )}
            {member && (
              <li>
                <Link to={`${base}/security`}>Two-step sign-in</Link>
              </li>
            )}
          </ul>
        </nav>
      </main>
    </>
  );
}

/** The old per-part addresses (still in links, bookmarks and the server's Home hrefs) land on the one page. */
export function ToBusinessSetup() {
  const { businessId = "" } = useParams();
  return <Navigate to={`/b/${businessId}/settings`} replace />;
}
