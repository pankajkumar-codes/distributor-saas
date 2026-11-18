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
import { useExports, useFilingProfile, useFreshLinks, useMakeFiles, type PeriodExport } from "./usePeriodFiles";

const FILE_LABEL = { workbook: "Excel workbook", purchase_register: "Purchase register (JSON)" } as const;

const today = () => new Date().toISOString().slice(0, 10);
const periodText = (e: PeriodExport) => `${e.period_start} to ${e.period_end}`;

/** The two files of one export, each with its own Download link, and what is in them. */
function Files({ businessId, exp }: { businessId: string; exp: PeriodExport }) {
  return (
    <div className="stack">
      <p className="hint">
        {periodText(exp)}: {exp.sales_lines} sales line{exp.sales_lines === 1 ? "" : "s"}, {exp.purchase_lines} purchase line
        {exp.purchase_lines === 1 ? "" : "s"}, {exp.practice_documents} practice document{exp.practice_documents === 1 ? "" : "s"} (listed apart, in no total).
      </p>
      <ul>
        {exp.files.map((f) => (
          <li key={f.name}>
            <a href={f.url} download aria-label={`Download ${FILE_LABEL[f.name]}, ${periodText(exp)}`}>
              Download {FILE_LABEL[f.name]}
            </a>{" "}
            <span className="hint">This link works for a minute; ask again if it has expired.</span>
          </li>
        ))}
      </ul>
      <p className="hint">Due dates: {exp.due_dates}.</p>
      {exp.gstr1_returns.map((r) => (
        <p key={r.instance_id} className="hint">
          The GSTR-1 file for sales is made from the return screen: <Link to={`/b/${businessId}/filing/${r.instance_id}`}>open the {r.form} return</Link>.
        </p>
      ))}
    </div>
  );
}

function PastRow({ businessId, exp }: { businessId: string; exp: PeriodExport }) {
  const fresh = useFreshLinks(businessId);
  return (
    <li>
      {exp.kind === "month" ? "Month" : "Quarter"}, {periodText(exp)} (made {exp.created_at.slice(0, 10)}){" "}
      <Button type="button" onClick={() => fresh.mutate(exp.id)} disabled={fresh.isPending} aria-label={`Get the files for ${periodText(exp)}`}>
        Get the files
      </Button>
      {fresh.error && <Banner tone="error">{errorText(fresh.error)}</Banner>}
      {fresh.data && <Files businessId={businessId} exp={fresh.data} />}
    </li>
  );
}

/**
 * Monthly and quarterly sales-and-purchases files (R2-M6): pick a finished month (or quarter, for a quarterly filer) and
 * download the Excel workbook and the purchase register. Nothing here is a return; the GSTR-1 file stays on the return
 * screen. The server decides what is allowed (the period has ended, the plan, the role); this screen only offers it.
 */
export function PeriodFilesPage() {
  const { businessId = "" } = useParams();
  const businesses = useMyBusinesses();
  const business = businesses.data?.find((b) => b.business_id === businessId);
  const allowed = Boolean(business && canPrepareReturns(business.role));
  const profile = useFilingProfile(businessId, allowed);
  const exports = useExports(businessId, allowed);
  const make = useMakeFiles(businessId);
  const quarterly = profile.data?.current?.frequency === "quarterly";
  const [kind, setKind] = useState<PeriodKind>("month");
  const [start, setStart] = useState("");
  const choices = finishedPeriods(kind, today());

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

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page">
        <h1>Monthly and quarterly files</h1>
        <p>
          <Link to={`/b/${businessId}/file-period`}>File from your own invoices</Link>
        </p>
        <p className="hint">
          After a month ends, get an Excel workbook of your sales and purchases and a purchase register. They are working files from your own records, not
          a return, and nothing in them is filed.
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            make.mutate({ kind, start });
          }}
        >
          {quarterly && (
            <SelectField
              label="For"
              value={kind}
              placeholder="Choose…"
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
          <SelectField label={kind === "month" ? "Month" : "Quarter"} value={start} options={choices.map((c) => ({ value: c.start, label: c.label }))} onChange={(e) => setStart(e.target.value)} />
          <Button type="submit" disabled={!start || make.isPending}>
            {make.isPending ? "Making the files…" : "Make the files"}
          </Button>
        </form>
        {make.error && <Banner tone="error">{errorText(make.error)}</Banner>}
        {make.data && (
          <>
            <Banner>{make.data.created ? "Your files are ready." : "Nothing has changed since these files were made, so here they are again."}</Banner>
            <Files businessId={businessId} exp={make.data} />
          </>
        )}
        <h2>Files made before</h2>
        {exports.error && <Banner tone="error">{errorText(exports.error)}</Banner>}
        {exports.data && exports.data.length === 0 && <p className="hint">None yet.</p>}
        <ul>{exports.data?.map((e) => <PastRow key={e.id} businessId={businessId} exp={e} />)}</ul>
      </main>
    </>
  );
}
