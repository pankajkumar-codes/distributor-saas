import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { errorText } from "../../api/errors";
import { canPrepareReturns } from "../../auth/roles";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { formatDate, formatDateTimeIst } from "../../format/dates";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { NotFound } from "../../kit/NotFound";
import { SelectField } from "../../kit/SelectField";
import { TopBar } from "../../kit/TopBar";
import { ExportPanel, type ExportJob } from "../filing/ExportPanel";
import { FiledPanel } from "../filing/FiledPanel";
import { useReturnDetail } from "../filing/returns";
import { finishedPeriods, type PeriodKind } from "./periods";
import { useConfirm, useGate, useNoSales, useOpenFile, type Gate, type GateItem } from "./useGate";
import { useFilingProfile } from "./usePeriodFiles";
import { NoAccess } from "../../kit/NoAccess";

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
  platform_files_missing: "Add the files of the marketplaces you sell on, or say there were no sales.",
  invoices_in_portal_stale: "Your invoices changed after you confirmed. Confirm again.",
};

const PLATFORM_NAME = { amazon: "Amazon", flipkart: "Flipkart", meesho: "Meesho" } as const;

const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
/** "2026-10" as "Oct 2026". */
const monthText = (ym: string) => `${MONTH_NAMES[Number(ym.slice(5, 7)) - 1] ?? ym.slice(5, 7)} ${ym.slice(0, 4)}`;

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
          {c.confirmed && !c.stale && c.at && <p className="hint">Confirmed on {formatDateTimeIst(c.at)}. This is kept in your audit log.</p>}
          {c.stale && <p className="hint">You confirmed this, but your records changed since. Tick it again once it is true.</p>}
        </div>
      ))}
      {confirm.error && <Banner tone="error">{errorText(confirm.error)}</Banner>}
    </fieldset>
  );
}

/**
 * The return the button opened, with its file and its lock right here: take the GSTR-1 file, file it on the GST portal, then say
 * when you filed it and the ARN, and the return is locked as it is. The same panels as the return screen, so the rules are the same.
 */
function ReturnControls({ businessId, instanceId, role }: { businessId: string; instanceId: string; role: string }) {
  const detail = useReturnDetail(businessId, instanceId);
  const [job, setJob] = useState<ExportJob>(null);
  if (detail.isPending) return <p aria-busy="true">Loading the return…</p>;
  if (detail.isError) return <Banner tone="error">{errorText(detail.error)}</Banner>;
  const d = detail.data;
  return (
    <div className="stack">
      <h3>
        {d.instance.form} return, {d.instance.period_label}
      </h3>
      {d.export && d.instance.status !== "filed_locked" && <ExportPanel businessId={businessId} instanceId={instanceId} gate={d.export} fingerprint={d.fingerprint} job={job && job.madeFor === d.fingerprint ? job : null} onJob={setJob} guideHref={`/b/${businessId}/filing/${instanceId}/portal-guide`} />}
      <FiledPanel businessId={businessId} instance={d.instance} role={role} />
      <p>
        <Link to={`/b/${businessId}/filing/${instanceId}`}>Open the full return</Link>
      </p>
    </div>
  );
}

/**
 * The marketplace-files step (R3-M4): only the platforms the business sells on, and only the months still missing. Each
 * month is met by uploading the file or by saying there were no sales there. Nothing shows when nothing is missing.
 */
function PlatformStep({ gate, businessId, kind, start }: { gate: Gate; businessId: string; kind: PeriodKind; start: string }) {
  const none = useNoSales(businessId, kind, start);
  if (gate.platform_files.length === 0) return null;
  return (
    <section aria-labelledby="platform-step" className="stack">
      <h2 id="platform-step">Marketplace files</h2>
      <p className="hint">You sell on more than one place, so each marketplace needs its file for every month of this period.</p>
      <ul>
        {gate.platform_files.flatMap((p) =>
          p.missing_months.map((m) => (
            <li key={`${p.platform}-${m}`}>
              {PLATFORM_NAME[p.platform]}, {monthText(m)}: no file yet.{" "}
              <Link to={`/b/${businessId}/uploads`}>Upload it</Link>{" "}
              <Button type="button" variant="link" disabled={none.isPending} onClick={() => none.mutate({ platform: p.platform, month: m })} aria-label={`No ${PLATFORM_NAME[p.platform]} sales in ${monthText(m)}`}>
                We had no sales there
              </Button>
            </li>
          )),
        )}
      </ul>
      {none.error && <Banner tone="error">{errorText(none.error)}</Banner>}
    </section>
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
  if (!business) return <NotFound />;
  if (!allowed) return <NoAccess businessId={businessId} />;
  const g = gate.data;
  const reasons = (g?.reasons ?? []).map((r) => REASON_TEXT[r] ?? "Not ready yet.");
  const opened = g?.gstr1_returns ?? [];

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
            <PlatformStep gate={g} businessId={businessId} kind={kind} start={start} />
            <p className="hint">Due date: {g.due_date ? formatDate(g.due_date) : g.due_dates}.</p>
            {!g.ended && <p className="hint">Filing for this period opens on {formatDate(g.opens_on)}.</p>}
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
              <section aria-labelledby="returns-h">
                <h2 id="returns-h">Your return</h2>
                <Banner>Your period is ready. Take the file, file it on the GST portal, then lock it here.</Banner>
                {opened.map((r) => (
                  <ReturnControls key={r.instance_id} businessId={businessId} instanceId={r.instance_id} role={business.role} />
                ))}
              </section>
            )}
          </>
        )}
      </main>
    </>
  );
}
