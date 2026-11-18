import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { api, call } from "../../api/client";
import type { ApiError } from "../../api/errors";
import { errorText } from "../../api/errors";
import type { components } from "../../api/schema";
import { SUPPORT_ROLE, useMyBusinesses } from "../../auth/useMyBusinesses";
import { formatDate } from "../../format/dates";
import { Banner } from "../../kit/Banner";
import { NotFound } from "../../kit/NotFound";
import { TopBar } from "../../kit/TopBar";
import { useChannels, type ChannelsOut } from "../uploads/useChannels";
import { AUDIT_VIEWERS } from "./AuditPage";
import { FREQUENCY_LABEL } from "./FilingPage";
import { SUPPORT_VIEWERS } from "./SupportPage";

type Profile = components["schemas"]["FilingProfileOut"];

const CHANNEL_NAMES: [keyof Omit<ChannelsOut, "answered">, string][] = [
  ["amazon", "Amazon"],
  ["flipkart", "Flipkart"],
  ["meesho", "Meesho"],
  ["own_invoices", "Your own sales invoices"],
];

/**
 * The settings front page at /b/:id/settings (R1 mocks, "Business setup"): where each setting lives, with what is set
 * now beside it. Read-only. Every change is made on the page it links to, where the server checks it, so nothing here
 * can disagree with them. A value that could not be loaded is left out and said so; the links still work.
 */
export function SettingsPage() {
  const { businessId = "" } = useParams();
  const businesses = useMyBusinesses();
  const business = businesses.data?.find((b) => b.business_id === businessId);
  const member = Boolean(business && business.role !== SUPPORT_ROLE);
  const channels = useChannels(businessId, member);
  const profile = useQuery<Profile, ApiError>({
    queryKey: ["b", businessId, "filing-profile"],
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/filing-profile", { params: { path: { business_id: businessId } } })),
    enabled: member,
  });

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
  const sells = channels.data && channels.data.answered ? CHANNEL_NAMES.filter(([k]) => channels.data[k]).map(([, n]) => n) : [];
  const current = profile.data?.current;

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page page-wide">
        <p className="step">
          <Link to={`/b/${businessId}/home`}>Home</Link>
        </p>
        <h1>Business setup</h1>
        <p className="hint">Change how you file or where you sell at any time. Each change is made on its own page.</p>

        <section className="card" aria-labelledby="set-details">
          <h2 id="set-details">Business details</h2>
          <p>
            {business.display_name}
            {business.gstin ? <> · GSTIN {business.gstin}</> : <> · No GSTIN saved yet</>}
          </p>
          <Link to={`${base}/company`}>Business details</Link>
        </section>

        {member && (
          <section className="card" aria-labelledby="set-sell">
            <h2 id="set-sell">Where you sell</h2>
            {channels.isPending && <p aria-busy="true">Loading…</p>}
            {channels.isError && <p className="hint">We couldn't load this. {errorText(channels.error)}</p>}
            {channels.data && (sells.length > 0 ? <p>{sells.join(", ")}</p> : <p className="hint">You haven't said where you sell yet.</p>)}
            <Link to={`${base}/company`}>Change where you sell</Link>
          </section>
        )}

        {member && (
          <section className="card" aria-labelledby="set-freq">
            <h2 id="set-freq">GST filing frequency</h2>
            {profile.isPending && <p aria-busy="true">Loading…</p>}
            {profile.isError && <p className="hint">We couldn't load this. {errorText(profile.error)}</p>}
            {profile.data && (current ? <p>{FREQUENCY_LABEL[current.frequency]}, from {formatDate(current.effective_from)}.</p> : <p className="hint">You haven't chosen how often you file yet.</p>)}
            <Link to={`${base}/filing`}>Change how often you file</Link>
          </section>
        )}

        <nav className="card" aria-labelledby="set-more">
          <h2 id="set-more">Access and security</h2>
          <ul className="list">
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
