import { Link, useParams } from "react-router-dom";

import { canPrepareReturns } from "../../auth/roles";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { previousFy } from "../../format/dates";
import { Banner } from "../../kit/Banner";
import { NotFound } from "../../kit/NotFound";
import { TopBar } from "../../kit/TopBar";
import { useReturns } from "./returns";

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

/** /b/:id/filing/:instanceId/portal-guide-3b: the steps for one GSTR-3B period. Needs `returns.prepare`, like the worksheet. */
export function Portal3bGuidePage() {
  const { businessId = "", instanceId = "" } = useParams();
  const businesses = useMyBusinesses();
  const business = businesses.data?.find((b) => b.business_id === businessId);
  const now = useReturns(businessId, undefined, Boolean(business));
  const found = now.data?.returns.find((r) => r.instance_id === instanceId);
  // A late return of last year is not in the current year's list: look there too, but only when it is not found yet.
  const before = useReturns(businessId, now.data ? previousFy(now.data.fy) : undefined, Boolean(business) && now.isSuccess && !found);
  const row = found ?? before.data?.returns.find((r) => r.instance_id === instanceId);

  if (businesses.isPending) {
    return (
      <main className="page" aria-busy="true">
        <p>Loading…</p>
      </main>
    );
  }
  if (!business || !canPrepareReturns(business.role)) return <NotFound />;
  const loading = now.isPending || (!found && now.isSuccess && before.isPending && before.fetchStatus !== "idle");
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
      <main className="page">
        <p className="step">
          <Link to={`/b/${businessId}/filing`}>Your GST filing</Link>
        </p>
        <h1>Enter GSTR-3B on the GST portal</h1>
        <p className="hint">Use your worksheet for {row.period_label}. You enter and submit it on the GST portal yourself.</p>
        <Banner>
          Do this after you have submitted your GSTR-1 on the portal. The outward figures on the portal follow your GSTR-1, so they should match this worksheet.{" "}
          <span className="chip chip-warn">To be confirmed</span>
        </Banner>
        <section className="card" aria-labelledby="steps-3b">
          <h2 id="steps-3b">Steps</h2>
          <ol>
            {GUIDE_3B_STEPS(row.period_label).map((text) => (
              <li key={text}>
                {text}{" "}
                <span className="chip chip-warn" title={GUIDE_3B_NOT_CHECKED}>
                  Not checked
                </span>
                <span className="hint"> {GUIDE_3B_NOT_CHECKED}</span>
              </li>
            ))}
          </ol>
          <p className="hint">
            Draft wording. The step order and screen names are checked against the live portal before launch, in the same test as the GSTR-1 guide. The official GSTR-3B Excel utility can also make a file for the portal's offline upload, for Tables 3.1, 3.1.1 and 3.2 only. Whether we offer that file in a later release is not decided.{" "}
            <span className="chip chip-warn">Not checked</span> We have not tried that utility.
          </p>
        </section>
      </main>
    </>
  );
}
