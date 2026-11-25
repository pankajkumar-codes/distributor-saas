import { Link, useParams } from "react-router-dom";

import { canViewReturns } from "../../auth/roles";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { Banner } from "../../kit/Banner";
import { NoAccess } from "../../kit/NoAccess";
import { NotFound } from "../../kit/NotFound";
import { Tabs } from "../../kit/Tabs";
import { TopBar } from "../../kit/TopBar";
import { GuideStep, GuideSwitch, useReturnRow } from "./guideShared";
import { LedgerHead, Panel, useTab } from "./ledger";
import { GUIDE_PARTS, GUIDE_STEPS } from "./PortalGuide";

/**
 * /b/:id/filing/:instanceId/portal-guide (mocks v16 "Portal guides", GSTR-1 upload). How to put the GSTR-1 file on the
 * GST portal, in two tabs so it fits one laptop screen. The steps and their "Not checked" notes are the same as before
 * (PortalGuide.tsx); only where they are shown changed.
 */
export function PortalGuidePage() {
  const { businessId = "", instanceId = "" } = useParams();
  const businesses = useMyBusinesses();
  const business = businesses.data?.find((b) => b.business_id === businessId);
  const may = Boolean(business && canViewReturns(business.role));
  const { row, loading, sibling } = useReturnRow(businessId, instanceId, may);
  const [tab, setTab] = useTab(["ready", "upload", "file"]);

  if (businesses.isPending) {
    return (
      <main className="page" aria-busy="true">
        <p>Loading…</p>
      </main>
    );
  }
  if (!business) return <NotFound />;
  if (!may) return <NoAccess businessId={businessId} />;
  if (loading) {
    return (
      <main className="page" aria-busy="true">
        <p>Loading…</p>
      </main>
    );
  }
  if (!row || row.form !== "GSTR1") return <NotFound />;
  const steps = GUIDE_STEPS(row.period_label);
  const list = (from: number, to: number) => (
    <ol className="path">
      {steps.slice(from, to).map((s, i) => (
        <GuideStep key={s.text} n={from + i + 1} text={s.text} check={s.check} />
      ))}
    </ol>
  );

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page page-wide ledger">
        <LedgerHead
          trail={
            <>
              <Link to={`/b/${businessId}/filing`}>Your GST filing</Link> / Portal guides
            </>
          }
          title="Upload GSTR-1 on the GST portal"
          lead={`For ${row.period_label}. You do these steps on the GST portal yourself. We don't file for you.`}
          actions={
            <Link className="btn btn-primary" to={`/b/${businessId}/filing/${row.instance_id}?tab=file`}>
              Back to GSTR-1
            </Link>
          }
        />
        <GuideSwitch businessId={businessId} current="gstr1" gstr1={row} gstr3b={sibling("GSTR3B")} />
        <Banner>
          These steps follow the GST Network's own guide for its offline tool. We have not checked them against the live portal yet, so a button may be named a little differently. Steps marked "Not checked" are the ones to look at twice.
        </Banner>
        <Tabs
          label="Steps"
          current={tab}
          onChange={setTab}
          tabs={GUIDE_PARTS.map(([key, name, from, to]) => {
            const end = Math.min(to, steps.length);
            return { key, label: `${name} (steps ${from + 1}–${end})`, panel: <Panel title={`${name}: steps ${from + 1} to ${end} of ${steps.length}`}>{list(from, end)}</Panel> };
          })}
        />
      </main>
    </>
  );
}
