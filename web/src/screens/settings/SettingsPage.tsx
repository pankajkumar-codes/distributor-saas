import { useQuery } from "@tanstack/react-query";
import { Link, Navigate, useLocation, useParams } from "react-router-dom";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { SUPPORT_ROLE, useMyBusinesses } from "../../auth/useMyBusinesses";
import { FEATURES } from "../../features";
import { formatDate } from "../../format/dates";
import { addressOf } from "../../kit/AddressFields";
import { Banner } from "../../kit/Banner";
import { NotFound } from "../../kit/NotFound";
import { TopBar } from "../../kit/TopBar";
import { BAND_OPTIONS } from "../onboarding/BusinessPage";
import { TEAM_MANAGERS } from "../team/TeamPage";
import { AUDIT_VIEWERS } from "./AuditPage";
import { CompanyPage, EDITORS } from "./CompanyPage";
import { FilingPage, FREQUENCY_LABEL } from "./FilingPage";
import { PlatformsSection } from "./PlatformsSection";
import { SettingsEyebrow } from "./SettingsEyebrow";
import { SUPPORT_VIEWERS } from "./SupportPage";

type Profile = components["schemas"]["ProfileOut"];
type FilingProfile = components["schemas"]["FilingProfileOut"];

function Panel({ title, action, children, id }: { title: string; action?: React.ReactNode; children: React.ReactNode; id: string }) {
  return (
    <section className="panel" aria-labelledby={id}>
      <div className="panel-h">
        <h2 id={id}>{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

function Kv({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="kv-row">
      <span>{label}</span>
      <span>{children}</span>
    </div>
  );
}

/** The address on one line, with the state's name rather than its code. */
function placeLine(p: Profile, stateName?: string | null): string {
  if (!p.address) return "—";
  const a = addressOf(p.address);
  const line = [a.line1, a.line2, a.city].map((x) => x.trim()).filter(Boolean).join(", ");
  const tail = [stateName, a.pin.trim()].filter(Boolean).join(" ");
  return [line, tail].filter(Boolean).join(", ") || "—";
}

/** Business details as they are saved; Change opens the form (mocks v16). */
function CompanySummary({ businessId, canEdit }: { businessId: string; canEdit: boolean }) {
  const profile = useQuery<Profile, ApiError>({
    queryKey: ["b", businessId, "profile"],
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/profile", { params: { path: { business_id: businessId } } })),
  });
  const p = profile.data;
  const reg = p?.registration;
  const band = p?.previous_turnover_band?.band;
  return (
    <Panel
      id="set-company"
      title="Business details"
      action={canEdit && <Link className="btn btn-secondary btn-sm" to="#company" aria-label="Change business details">Change</Link>}
    >
      {profile.isPending && <p className="pad hint">Loading…</p>}
      {profile.isError && <p className="pad">{errorText(profile.error)}</p>}
      {p && (
        <>
          <Kv label="Legal name">{p.legal_name || "—"}</Kv>
          {p.trade_name && <Kv label="Trade name">{p.trade_name}</Kv>}
          <Kv label={reg?.kind === "gstin" ? "GSTIN" : "Enrolment number"}>
            <span className="num">{(reg?.kind === "gstin" ? reg.gstin : reg?.enrolment_number) ?? "—"}</span>
          </Kv>
          <Kv label="Address">{placeLine(p, reg?.state_name)}</Kv>
          <Kv label="Turnover last year">{BAND_OPTIONS.find((o) => o.value === band)?.label ?? "Not set yet"}</Kv>
        </>
      )}
    </Panel>
  );
}

/** The filing frequency as it is saved; Change opens the chooser. */
function FilingSummary({ businessId, canEdit }: { businessId: string; canEdit: boolean }) {
  const profile = useQuery<FilingProfile, ApiError>({
    queryKey: ["b", businessId, "filing-profile"],
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/filing-profile", { params: { path: { business_id: businessId } } })),
  });
  const cur = profile.data?.current;
  return (
    <Panel
      id="set-filing"
      title="Filing frequency"
      action={canEdit && profile.data?.gstin && <Link className="btn btn-secondary btn-sm" to="#filing" aria-label="Change filing frequency">Change</Link>}
    >
      {profile.isPending && <p className="pad hint">Loading…</p>}
      {profile.isError && <p className="pad">{errorText(profile.error)}</p>}
      {profile.data && (
        <Kv label="How often you file">
          {cur
            ? `${FREQUENCY_LABEL[cur.frequency as keyof typeof FREQUENCY_LABEL] ?? cur.frequency}, from ${formatDate(cur.effective_from)}.`
            : "You haven't chosen a filing frequency yet."}
        </Kv>
      )}
    </Panel>
  );
}

/**
 * Business setup at /b/:id/settings (mocks v16): what is saved, in panels, each with Change; where you
 * sell; and the Settings sub-menu (team, support access, audit log, two-step sign-in, invoicing plan),
 * so the sidebar keeps one Settings item. Change opens that part's own form on this page (#company,
 * #filing); each part keeps its own server calls and Save, so one part failing never loses another's
 * edits. The old /settings/company and /settings/filing addresses open those forms.
 */
export function SettingsPage() {
  const { businessId = "" } = useParams();
  const { hash, state } = useLocation();
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
  const canEdit = EDITORS.has(business.role);
  // An invoice that needs last year's band sends people straight to the business details form.
  const fromInvoice = Boolean((state as { backTo?: unknown } | null)?.backTo) || hash === "#last-year-band";
  const part = !member ? null : hash === "#company" || fromInvoice ? "company" : hash === "#filing" ? "filing" : null;

  const more = (
    <Panel id="set-more" title="Team, security and plan">
      <ul className="pad link-row">
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
        {member && FEATURES.invoicing && (
          <li>
            <Link to={`${base}/plan`}>Invoicing plan</Link>
          </li>
        )}
      </ul>
    </Panel>
  );

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page page-wide">
        <SettingsEyebrow businessId={businessId} />
        <h1>Business setup</h1>
        {/* While a part's form is open, the lead gives way so the form fits one laptop screen (#404). */}
        {!part && <p className="lead">Change how you file or where you sell at any time. Deadlines update straight away.</p>}

        {part ? (
          <>
            <p className="back">
              <Link to={base}>Back to Business setup</Link>
            </p>
            <div className="panel pad setup-edit">{part === "company" ? <CompanyPage embedded /> : <FilingPage embedded />}</div>
          </>
        ) : (
          <div className="grid2 setup-grid">
            {member && <CompanySummary businessId={businessId} canEdit={canEdit} />}
            {member && <FilingSummary businessId={businessId} canEdit={canEdit} />}
            {member && <PlatformsSection businessId={businessId} canEdit={canEdit} />}
            {more}
          </div>
        )}
      </main>
    </>
  );
}

/** The old per-part addresses (still in links, bookmarks and the server's Home hrefs) open that part's form here. */
export function ToBusinessSetup({ part }: { part?: "company" | "filing" }) {
  const { businessId = "" } = useParams();
  return <Navigate to={`/b/${businessId}/settings${part ? `#${part}` : ""}`} replace />;
}
