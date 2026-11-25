import { Link, useParams } from "react-router-dom";

import { canViewReturns } from "../../auth/roles";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { Banner } from "../../kit/Banner";
import { NotFound } from "../../kit/NotFound";
import { TopBar } from "../../kit/TopBar";
import { GuideStep, GuideSwitch, useReturnRow } from "./guideShared";
import { LedgerHead, Panel } from "./ledger";
import { NoAccess } from "../../kit/NoAccess";

/**
 * How to enter the GSTR-3B worksheet on the GST portal (R1-M8b, W5c; mock `w3bg`). Nobody here has opened the live GSTR-3B
 * screens for this, so every step carries the "Not checked" mark until the portal test, and the page says so. The wording
 * never says a return is "filed" or "ready to file" by us: the person enters and submits it on the portal themselves.
 */
export const GUIDE_3B_STEPS = (periodLabel: string): string[] => [
  "Sign in to the GST portal with your own login. We never ask for it.",
  `Open the Returns Dashboard, choose "${periodLabel}", and open GSTR-3B.`,
  "Check the outward supplies the portal already shows against Table 3.1(a) of your worksheet. If they differ, stop and look at your GSTR-1 first.",
  "Enter your input tax credit in Table 4 from the figures you typed on your worksheet.",
  "Look at the tax the portal shows for payment. The portal works out the cash amount; this worksheet does not.",
  "Pay any balance on the portal, then submit the return there yourself with your usual signature or OTP.",
];

export const GUIDE_3B_NOT_CHECKED = "Not checked on the live portal yet.";

/** /b/:id/filing/:instanceId/portal-guide-3b (mocks v16 "Portal guides", GSTR-3B entry): the steps for one GSTR-3B period. */
export function Portal3bGuidePage() {
  const { businessId = "", instanceId = "" } = useParams();
  const businesses = useMyBusinesses();
  const business = businesses.data?.find((b) => b.business_id === businessId);
  const may = Boolean(business && canViewReturns(business.role));
  const { row, loading, sibling } = useReturnRow(businessId, instanceId, may);

  if (businesses.isPending) {
    return (
      <main className="page" aria-busy="true">
        <p>Loading…</p>
      </main>
    );
  }
  if (!business) return <NotFound />;
  if (!canViewReturns(business.role)) return <NoAccess businessId={businessId} />;
  if (loading) {
    return (
      <main className="page" aria-busy="true">
        <p>Loading…</p>
      </main>
    );
  }
  if (!row || row.form !== "GSTR3B") return <NotFound />;

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
          title="Enter GSTR-3B on the GST portal"
          lead={`Use your worksheet for ${row.period_label}. You enter and submit it on the GST portal yourself.`}
          actions={
            <Link className="btn btn-primary" to={`/b/${businessId}/filing/${row.instance_id}/worksheet`}>
              Back to the worksheet
            </Link>
          }
        />
        <GuideSwitch businessId={businessId} current="gstr3b" gstr1={sibling("GSTR1")} gstr3b={row} />
        <Banner>
          Do this after you have submitted your GSTR-1 on the portal. The outward figures on the portal follow your GSTR-1, so they should match this worksheet.{" "}
          <span className="chip chip-warn">To be confirmed</span> Every step below is marked “Not checked”: {GUIDE_3B_NOT_CHECKED.toLowerCase()}
        </Banner>
        <Panel title={`${GUIDE_3B_STEPS(row.period_label).length} steps`}>
          <ol className="path">
            {GUIDE_3B_STEPS(row.period_label).map((text, i) => (
              <GuideStep key={text} n={i + 1} text={text} mark={GUIDE_3B_NOT_CHECKED} />
            ))}
          </ol>
          <p className="pad hint">
            Draft wording. The step order and screen names are checked against the live portal before launch, in the same test as the GSTR-1 guide. The official GSTR-3B Excel utility can also make a file for the portal's offline upload, for Tables 3.1, 3.1.1 and 3.2 only. Whether we offer that file in a later release is not decided.{" "}
            <span className="chip chip-warn">Not checked</span> We have not tried that utility.
          </p>
        </Panel>
      </main>
    </>
  );
}
