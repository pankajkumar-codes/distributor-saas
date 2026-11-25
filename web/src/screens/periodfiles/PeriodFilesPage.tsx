import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { errorText } from "../../api/errors";
import { canPrepareReturns } from "../../auth/roles";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { NotFound } from "../../kit/NotFound";
import { SelectField } from "../../kit/SelectField";
import { Pager } from "../../kit/Pager";
import { TopBar } from "../../kit/TopBar";
import { formatDate } from "../../format/dates";
import { LedgerHead, Panel } from "../filing/ledger";
import { finishedPeriods, type PeriodKind } from "./periods";
import { useExports, useFilingProfile, useFreshLinks, useMakeFiles, type PeriodExport } from "./usePeriodFiles";
import { NoAccess } from "../../kit/NoAccess";

const FILE_LABEL = { workbook: "Excel workbook", purchase_register: "Purchase register (JSON)" } as const;

const today = () => new Date().toISOString().slice(0, 10);
const periodText = (e: PeriodExport) => `${e.period_start} to ${e.period_end}`;

/** The two files of one export, each with its own Download link, and what is in them. */
function Files({ businessId, exp }: { businessId: string; exp: PeriodExport }) {
  return (
    <div className="files-made">
      <p className="hint">
        {periodText(exp)}: <span className="num">{exp.sales_lines}</span> sales line{exp.sales_lines === 1 ? "" : "s"}, <span className="num">{exp.purchase_lines}</span> purchase line
        {exp.purchase_lines === 1 ? "" : "s"}, <span className="num">{exp.practice_documents}</span> practice document{exp.practice_documents === 1 ? "" : "s"} (listed apart, in no total).
        Due dates: {exp.due_dates}.
      </p>
      <p className="dl-links">
        {exp.files.map((f, i) => (
          <span key={f.name}>
            {i > 0 && " · "}
            <a href={f.url} download aria-label={`Download ${FILE_LABEL[f.name]}, ${periodText(exp)}`}>
              Download {FILE_LABEL[f.name]}
            </a>
          </span>
        ))}
      </p>
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
    <>
      <tr>
        <td>
          {exp.kind === "month" ? "Month" : "Quarter"}, <span className="num">{periodText(exp)}</span>
        </td>
        <td className="num">{formatDate(exp.created_at.slice(0, 10))}</td>
        <td className="r">
          <Button type="button" variant="secondary" className="btn-sm" onClick={() => fresh.mutate(exp.id)} disabled={fresh.isPending} aria-label={`Get the files for ${periodText(exp)}`}>
            Get the files
          </Button>
        </td>
      </tr>
      {(fresh.error || fresh.data) && (
        <tr>
          <td colSpan={3}>
            {fresh.error && <Banner tone="error">{errorText(fresh.error)}</Banner>}
            {fresh.data && <Files businessId={businessId} exp={fresh.data} />}
          </td>
        </tr>
      )}
    </>
  );
}

const PAST_PAGE = 4;

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
  const [page, setPage] = useState(0);
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
  if (!business) return <NotFound />;
  if (!allowed) return <NoAccess businessId={businessId} />;

  const past = exports.data ?? [];
  const pastSlice = past.slice(page * PAST_PAGE, (page + 1) * PAST_PAGE);

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page page-wide ledger">
        <LedgerHead
          trail={
            <>
              <Link to={`/b/${businessId}/filing`}>GST filing</Link> / Monthly and quarterly files
            </>
          }
          title="Monthly and quarterly files"
          lead="An Excel workbook and a purchase register for a month or a quarter, for you or your CA. They are working files, not a return."
          actions={
            <Link className="btn btn-secondary" to={`/b/${businessId}/file-period`}>
              File from your own invoices
            </Link>
          }
        />
        <section className="panel pad" aria-label="Make the files">
          <form
            className="f-line"
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
        </section>
        <Panel title="Files made before" aside={<span className="hint">Download links work for a minute; ask again if one has expired.</span>}>
          {exports.error && <Banner tone="error">{errorText(exports.error)}</Banner>}
          {exports.data && past.length === 0 && <p className="pad hint">None yet.</p>}
          {past.length > 0 && (
            <>
              <div className="tablewrap">
                <table className="lt dense">
                  <thead>
                    <tr>
                      <th scope="col">Period</th>
                      <th scope="col">Made</th>
                      <th scope="col" className="r">
                        Files
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {pastSlice.map((e) => (
                      <PastRow key={e.id} businessId={businessId} exp={e} />
                    ))}
                  </tbody>
                </table>
              </div>
              {past.length > PAST_PAGE && <Pager page={page} size={PAST_PAGE} shown={pastSlice.length} total={past.length} noun="files made before" onPage={setPage} />}
            </>
          )}
        </Panel>
      </main>
    </>
  );
}
