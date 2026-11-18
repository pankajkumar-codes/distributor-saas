import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { errorText } from "../../api/errors";
import { canPrepareReturns } from "../../auth/roles";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { NotFound } from "../../kit/NotFound";
import { SelectField } from "../../kit/SelectField";
import { TopBar } from "../../kit/TopBar";
import { finishedPeriods, type PeriodKind } from "./periods";
import { useConfirm, useGate, useOpenFile, type Gate, type GateItem } from "./useGate";
import { useFilingProfile } from "./usePeriodFiles";

const ITEM_TEXT: Record<GateItem, string> = {
  purchases_uploaded: "I have uploaded all my purchase invoices for this period",
  invoices_in_portal: "Every invoice for this period is in the portal",
};

/** Why the button is closed, in words, for each code the server gives. */
const REASON_TEXT: Record<string, string> = {
  period_not_ended: "This period has not ended yet.",
  purchases_uploaded_missing: "Confirm that all your purchase invoices are uploaded.",
  invoices_in_portal_missing: "Confirm that every invoice is in the portal.",
  purchases_uploaded_stale: "Your purchase invoices or sales changed after you confirmed. Confirm again.",
  invoices_in_portal_stale: "Your invoices changed after you confirmed. Confirm again.",
};

const today = () => new Date().toISOString().slice(0, 10);

function Checks({ gate, businessId, kind, start }: { gate: Gate; businessId: string; kind: PeriodKind; start: string }) {
  const confirm = useConfirm(businessId, kind, start);
  return (
    <fieldset disabled={confirm.isPending || !gate.ended}>
      <legend>Before you file</legend>
      {gate.confirmations.map((c) => (
        <div key={c.item}>
          <label>
            <input type="checkbox" checked={c.confirmed && !c.stale} onChange={(e) => confirm.mutate({ item: c.item, confirmed: e.target.checked })} /> {ITEM_TEXT[c.item]}
          </label>
          {c.stale && <p className="hint">You confirmed this, but your records changed since. Tick it again once it is true.</p>}
        </div>
      ))}
      {confirm.error && <Banner tone="error">{errorText(confirm.error)}</Banner>}
    </fieldset>
  );
}

/**
 * File from your own invoices (R3-M1, R3-M2): pick a month (or quarter), confirm the two things, then press the button. The
 * server says whether the button is open and why not; this screen shows it. It opens only after the period has ended.
 */
export function FilePeriodPage() {
  const { businessId = "" } = useParams();
  const businesses = useMyBusinesses();
  const business = businesses.data?.find((b) => b.business_id === businessId);
  const allowed = Boolean(business && canPrepareReturns(business.role));
  const profile = useFilingProfile(businessId, allowed);
  const quarterly = profile.data?.current?.frequency === "quarterly";
  const [kind, setKind] = useState<PeriodKind>("month");
  const [start, setStart] = useState("");
  const gate = useGate(businessId, kind, start, allowed);
  const open = useOpenFile(businessId, kind, start);

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
  if (!business || !allowed) return <NotFound />;
  const g = gate.data;
  const reasons = (g?.reasons ?? []).map((r) => REASON_TEXT[r] ?? "Not ready yet.");
  const opened = open.data?.gstr1_returns ?? [];

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page">
        <h1>File from your own invoices</h1>
        <p className="hint">Choose the period, confirm the two checks, then get your GSTR-1 file. We don't file for you: you upload the file on the GST portal.</p>
        {quarterly && (
          <SelectField
            label="For"
            value={kind}
            options={[
              { value: "month", label: "A month" },
              { value: "quarter", label: "A quarter" },
            ]}
            onChange={(e) => {
              setKind((e.target.value || "month") as PeriodKind);
              setStart("");
            }}
          />
        )}
        <SelectField
          label={kind === "month" ? "Month" : "Quarter"}
          value={start}
          options={finishedPeriods(kind, today(), 12, true).map((c) => ({ value: c.start, label: c.label }))}
          onChange={(e) => setStart(e.target.value)}
        />
        {gate.error && <Banner tone="error">{errorText(gate.error)}</Banner>}
        {g && (
          <>
            <Checks gate={g} businessId={businessId} kind={kind} start={start} />
            <p className="hint">Due date: {g.due_date ?? g.due_dates}.</p>
            {!g.ended && <p className="hint">Filing for this period opens on {g.opens_on}.</p>}
            <Button type="button" disabled={!g.can_file || open.isPending} onClick={() => open.mutate()}>
              {open.isPending ? "Getting your file…" : "Get my GSTR-1 file"}
            </Button>
            {!g.can_file && reasons.length > 0 && (
              <ul className="hint">
                {reasons.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            )}
            {open.error && <Banner tone="error">{errorText(open.error)}</Banner>}
            {opened.length > 0 && (
              <div className="stack">
                <Banner>Your period is ready. Open the return to download the file.</Banner>
                <ul>
                  {opened.map((r) => (
                    <li key={r.instance_id}>
                      <Link to={`/b/${businessId}/filing/${r.instance_id}`}>
                        Open the {r.form} return, {r.period_start} to {r.period_end}
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </main>
    </>
  );
}
