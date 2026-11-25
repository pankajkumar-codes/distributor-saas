import { useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";

import { errorText, type ApiError } from "../../api/errors";
import { canPrepareReturns } from "../../auth/roles";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { formatDateTimeIst } from "../../format/dates";
import { formatRupees } from "../../format/money";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { NotFound } from "../../kit/NotFound";
import { Tabs } from "../../kit/Tabs";
import { TopBar } from "../../kit/TopBar";
import { useBuildWorksheet, useSaveEntries, useStartWorksheetPdf, useWorksheetExcel, useWorksheetPdfStatus, useWorksheet, type Outward, type Worksheet } from "./worksheet";
import { HEAD_NAME, TABLES, typedHeads, type Head, type Table } from "./worksheetRows";
import { NoAccess } from "../../kit/NoAccess";
import { Loading } from "../../kit/Loading";
import { useReturnRow } from "./guideShared";
import { LedgerHead, Panel, amountOrDash, useTab } from "./ledger";

/** The server fills state/UT tax from central tax on those rows, so only the typed boxes are kept and sent back. */
const typedOnly = (entries: Record<string, string>) => {
  const out: Record<string, string> = {};
  for (const t of TABLES) for (const r of t.rows) for (const h of typedHeads(r)) { const v = entries[`${t.id}.${r.key}.${h}`]; if (v !== undefined) out[`${t.id}.${r.key}.${h}`] = v; }
  return out;
};

/** The Excel file holds the build and what was last saved; an unsaved box is not in it. */
function ExcelButton({ businessId, instanceId }: { businessId: string; instanceId: string }) {
  const excel = useWorksheetExcel(businessId, instanceId);
  return (
    <>
      <Button
        variant="secondary"
        className="btn-sm"
        busy={excel.isPending}
        title="The file has what you have saved, not boxes you are still typing in."
        onClick={() => excel.mutate(undefined, { onSuccess: (r) => window.location.assign(r.url) })}
      >
        Download as Excel
      </Button>
      {excel.isError && <Banner tone="error">{errorText(excel.error)}</Banner>}
    </>
  );
}

/** The PDF is made in the background: queued, rendering, then a 60-second link. It holds what was last saved too. */
function PdfButton({ businessId, instanceId }: { businessId: string; instanceId: string }) {
  const [jobId, setJobId] = useState<string | null>(null);
  const start = useStartWorksheetPdf(businessId, instanceId);
  const status = useWorksheetPdfStatus(businessId, instanceId, jobId);
  const s = status.data?.status;
  const working = start.isPending || (!status.isError && (s === "queued" || s === "rendering"));
  return (
    <>
      <Button variant="secondary" className="btn-sm" busy={working} onClick={() => start.mutate(undefined, { onSuccess: (r) => setJobId(r.job_id) })}>
        {working ? "Making the PDF…" : "Make a PDF"}
      </Button>
      {s === "ready" && status.data?.url && (
        <span className="hint">
          <a href={status.data.url}>Download the PDF</a> The link works for 60 seconds.
        </span>
      )}
      {start.isError && <Banner tone="error">We couldn't make the PDF. {errorText(start.error)}</Banner>}
      {(s === "failed" || status.isError) && <Banner tone="error">We couldn't make the PDF. Try again. Nothing was lost.</Banner>}
    </>
  );
}

const TAX_HEADS = ["igst", "cgst", "sgst", "cess"] as const;
const NOT_BUILT = "Not built from your uploads yet. Check it on the GST portal.";
const COLS: Head[] = ["taxable_value", "igst", "cgst", "sgst", "cess"];
const byId = (id: string) => TABLES.find((t) => t.id === id)!;

type Entry = {
  values: Record<string, string>;
  set: (name: string, v: string) => void;
  err: ApiError | null;
};

/** The label a box is read out with: the column and the row, as the portal names them. */
const boxLabel = (h: Head, rowLabel: string, copy?: boolean) => `${h === "cgst" && copy ? "Central Tax (State/UT Tax is the same)" : HEAD_NAME[h]}, ${rowLabel}`;

/** One typed row as table cells: a box per head the seller types; on a `copy` row the State/UT cell says it follows Central. */
function EntryCells({ table, rowKey, entry, cols }: { table: Table; rowKey: string; entry: Entry; cols: Head[] }) {
  const r = table.rows.find((x) => x.key === rowKey)!;
  const typed = typedHeads(r);
  return (
    <>
      {cols.map((h) => {
        const name = `${table.id}.${r.key}.${h}`;
        if (!r.heads.includes(h)) return <td key={h} className="r" />;
        if (!typed.includes(h)) {
          return (
            <td key={h} className="r sub2">
              Same as Central
            </td>
          );
        }
        const e = entry.err;
        const error = e?.field === name || (r.copy && h === "cgst" && e?.field === `${table.id}.${r.key}.sgst`) ? (e.fix ?? e.message) : undefined;
        return (
          <td key={h} className="r">
            <input
              aria-label={boxLabel(h, r.label, r.copy)}
              inputMode="decimal"
              autoComplete="off"
              className="num"
              value={entry.values[name] ?? ""}
              onChange={(ev) => entry.set(name, ev.target.value)}
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? `${name}-err` : undefined}
            />
            {error && (
              <div className="error" id={`${name}-err`}>
                {error}
              </div>
            )}
          </td>
        );
      })}
    </>
  );
}

function EntryTable({ tables, entry, cols = COLS, first = "Nature of supplies", foot }: { tables: Table[]; entry: Entry; cols?: Head[]; first?: string; foot?: ReactNode }) {
  return (
    <div className="tablewrap">
      <table className="lt dense ws">
        <thead>
          <tr>
            <th scope="col">{first}</th>
            {cols.map((h) => (
              <th scope="col" className="r" key={h}>
                {HEAD_NAME[h]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {tables.flatMap((t) => [
            ...(tables.length > 1
              ? [
                  <tr key={t.id} className="grp">
                    <th scope="rowgroup" colSpan={cols.length + 1}>
                      {t.title}
                      {t.hint && <span className="sub2"> {t.hint}</span>}
                    </th>
                  </tr>,
                ]
              : []),
            ...t.rows.map((r) => (
              <tr key={`${t.id}.${r.key}`}>
                <th scope="row" className="rowname">
                  {r.label}
                </th>
                <EntryCells table={t} rowKey={r.key} entry={entry} cols={cols} />
              </tr>
            )),
          ])}
        </tbody>
        {foot}
      </table>
    </div>
  );
}

function Outward31({ o, entry }: { o: Outward | null; entry: Entry }) {
  const t31 = byId("t3_1");
  const fig = (v: string | undefined) => <td className="r num">{o && v !== undefined ? amountOrDash(v) : "—"}</td>;
  return (
    <>
      {o && o.flags.length > 0 && (
        <Banner tone="warn">
          <b>Please check {o.flags.length === 1 ? "this" : `these ${o.flags.length}`}.</b> {o.flags.map((f) => f.text).join(" ")}
        </Banner>
      )}
      <Panel title="3.1 Outward supplies, from your invoices" aside={o && <span className="hint">Build {o.version}, made {formatDateTimeIst(o.built_at)}. From {o.taxable_refs.length} source {o.taxable_refs.length === 1 ? "row" : "rows"}.</span>}>
        <div className="tablewrap">
          <table className="lt dense ws">
            <thead>
              <tr>
                <th scope="col">Nature of supplies</th>
                {COLS.map((h) => (
                  <th scope="col" className="r" key={h}>
                    {HEAD_NAME[h]}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr>
                <th scope="row" className="rowname">
                  (a) Outward taxable supplies (other than zero rated, nil rated and exempted)
                </th>
                {fig(o?.taxable.taxable_value)}
                {fig(o?.taxable.igst)}
                {fig(o?.taxable.cgst)}
                {fig(o?.taxable.sgst)}
                {fig(o?.taxable.cess)}
              </tr>
              <tr>
                <th scope="row" className="rowname">
                  (b) Zero rated, (c) nil rated or exempted, (e) non-GST
                </th>
                <td colSpan={COLS.length} className="sub2">
                  {NOT_BUILT}
                </td>
              </tr>
              {t31.rows.map((r) => (
                <tr key={r.key}>
                  <th scope="row" className="rowname">
                    {r.label} <span className="sub2">Type it. We do not work it out.</span>
                  </th>
                  <EntryCells table={t31} rowKey={r.key} entry={entry} cols={COLS} />
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="pad hint">3.1.1 Supplies notified under section 9(5): check on the GST portal.</p>
      </Panel>
    </>
  );
}

function Inter32({ o }: { o: Outward | null }) {
  return (
    <Panel title="3.2 Inter-state supplies to unregistered buyers">
      {!o ? (
        <p className="pad">The outward supplies have not been built yet.</p>
      ) : o.inter_state.length === 0 ? (
        <p className="pad">No inter-state supplies to unregistered buyers in this period.</p>
      ) : (
        <div className="tablewrap">
          <table className="lt">
            <thead>
              <tr>
                <th scope="col">Place of supply</th>
                <th scope="col" className="r">
                  Taxable value
                </th>
                <th scope="col" className="r">
                  Integrated Tax
                </th>
              </tr>
            </thead>
            <tbody>
              {o.inter_state.map((r) => (
                <tr key={r.pos_state_code}>
                  <td>State code {r.pos_state_code}</td>
                  <td className="r num">{formatRupees(r.unregistered_taxable)}</td>
                  <td className="r num">{formatRupees(r.unregistered_igst)}</td>
                </tr>
              ))}
              <tr>
                <td>
                  <b>Total</b>
                </td>
                <td className="r num">
                  <b>{formatRupees(o.inter_state_taxable)}</b>
                </td>
                <td className="r num">
                  <b>{formatRupees(o.inter_state_igst)}</b>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

/** What the seller types, across the tabs. The boxes keep what was typed, also when someone else has saved in the meantime. */
function WorksheetForm({ businessId, instanceId, ws, tab, onTab }: { businessId: string; instanceId: string; ws: Worksheet; tab: number; onTab: (i: number) => void }) {
  const save = useSaveEntries(businessId, instanceId);
  const [values, setValues] = useState<Record<string, string>>(() => typedOnly(ws.entries));
  const [saved, setSaved] = useState(false);
  // The save these boxes were last in step with. A second save from an old one is refused by the server, so a stale
  // form can never overwrite what someone else saved without the person choosing to see it first.
  const [baseSeq, setBaseSeq] = useState<number | null>(ws.entries_seq);
  const err: ApiError | null = save.error;
  const entry: Entry = {
    values,
    err,
    set: (name, v) => {
      setSaved(false);
      setValues((cur) => ({ ...cur, [name]: v }));
    },
  };
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const entries: Record<string, string> = {};
    for (const [k, v] of Object.entries(values)) if (v.trim() !== "") entries[k] = v;
    save.mutate(
      { entries, based_on_seq: baseSeq },
      {
        onSuccess: (r) => {
          setBaseSeq(r.entries_seq);
          setSaved(true);
        },
      },
    );
  };
  const showSaved = () => {
    setValues(typedOnly(ws.entries));
    setBaseSeq(ws.entries_seq);
    setSaved(false);
    save.reset();
  };
  const stale = err?.code === "worksheet_changed";
  const o = ws.outward;
  const tabs: { key: string; label: ReactNode; panel: ReactNode }[] = [
    { key: "31", label: "3.1 Outward", panel: <Outward31 o={o} entry={entry} /> },
    { key: "32", label: "3.2 Inter-state", panel: <Inter32 o={o} /> },
    {
      key: "4a",
      label: "4(A) Credit",
      panel: (
        <Panel title="4(A) ITC available" aside={<span className="hint">From your GSTR-2B on the GST portal.</span>}>
          <EntryTable
            tables={[byId("t4a")]}
            entry={entry}
            cols={TAX_HEADS.slice()}
            first="Details"
            foot={
              Object.keys(ws.net_itc).length > 0 && (
                <tfoot>
                  <tr>
                    <th scope="row" className="rowname">
                      4(C) Net ITC, from what you saved <span className="sub2">Available minus reversed. For your reference only.</span>
                    </th>
                    {TAX_HEADS.map((h) => (
                      <td className="r num" key={h}>
                        {amountOrDash(ws.net_itc[h])}
                      </td>
                    ))}
                  </tr>
                </tfoot>
              )
            }
          />
        </Panel>
      ),
    },
    {
      key: "4bd",
      label: "4(B), 4(D) Reversed",
      panel: (
        <Panel title="4(B) ITC reversed and 4(D) other details">
          <EntryTable tables={[byId("t4b"), byId("t4d")]} entry={entry} cols={TAX_HEADS.slice()} first="Details" />
        </Panel>
      ),
    },
    {
      key: "5",
      label: "5 Exempt and interest",
      panel: (
        <div className="grid2">
          <Panel title="5 Exempt, nil-rated and non-GST inward supplies">
            <EntryTable tables={[byId("t5")]} entry={entry} cols={["inter", "intra"]} first="Nature of supplies" />
          </Panel>
          <Panel title="5.1 Interest" aside={<span className="hint">Type it if the portal shows any.</span>}>
            <EntryTable tables={[byId("t5_1")]} entry={entry} cols={TAX_HEADS.slice()} first="Details" />
            <p className="pad hint">We never work out interest or late fee.</p>
          </Panel>
        </div>
      ),
    },
  ];
  return (
    <form onSubmit={submit} noValidate aria-label="What you enter yourself">
      <Tabs label="GSTR-3B tables" tabs={tabs} current={tab} onChange={onTab} keepMounted />
      <div className="bar">
        <Button type="submit" variant={ws.built ? "primary" : "secondary"} busy={save.isPending}>
          Save what I entered
        </Button>
        {saved && <Banner>Saved.</Banner>}
        {stale && (
          <Banner tone="error">
            Your changes were not saved. Someone else saved this worksheet while you were typing. Your boxes still show what you typed.{" "}
            <Button type="button" variant="secondary" className="btn-sm" onClick={showSaved}>
              Show what was saved instead
            </Button>
          </Banner>
        )}
        {err && !err.field && !stale && <Banner tone="error">{errorText(err)}</Banner>}
        {err?.field && <Banner tone="error">Some amounts need a change. {errorText(err)}</Banner>}
        {!saved && !err && <span className="hint">Saves the boxes on every tab. The boxes are typed by you: we keep them and show them back, and do not check them against the GST rules. Leave a box empty if it is nil.</span>}
      </div>
    </form>
  );
}

export const WORKSHEET_TABS = ["31", "32", "4a", "4bd", "5"];

/** /b/:id/filing/:instanceId/worksheet (R1-M8b W4; mocks v16 "GSTR-3B worksheet"): numbers to check and enter on the GST portal, in tabs. Never a filing. */
export function WorksheetPage() {
  const { businessId = "", instanceId = "" } = useParams();
  const businesses = useMyBusinesses();
  const business = businesses.data?.find((b) => b.business_id === businessId);
  const allowed = business !== undefined && canPrepareReturns(business.role);
  const q = useWorksheet(businessId, instanceId, allowed);
  const build = useBuildWorksheet(businessId, instanceId);
  const { row } = useReturnRow(businessId, instanceId, allowed);
  const [tab, setTab] = useTab(WORKSHEET_TABS);

  if (businesses.isPending) {
    return (
      <main className="page" aria-busy="true">
        <p>Loading…</p>
      </main>
    );
  }
  if (!business) return <NotFound />;
  if (!allowed || (q.isError && q.error.status === 404)) return <NoAccess businessId={businessId} />;
  const ws = q.data;

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page page-wide ledger">
        <LedgerHead
          trail={
            <>
              <Link to={`/b/${businessId}/filing`}>Your GST filing</Link> / GSTR-3B worksheet
              {ws && <span className="chip chip-warn">{ws.label}</span>}
            </>
          }
          title={row ? `GSTR-3B worksheet, ${row.period_label}` : "GSTR-3B worksheet"}
          lead={ws ? `${ws.note} ${ws.offset_note} Nothing here is sent to the portal.` : undefined}
          actions={
            <>
              {ws?.available && ws.built && (
                <>
                  <Button variant="secondary" className="btn-sm" disabled={!ws.can_build} busy={build.isPending} onClick={() => build.mutate()} title="The Excel file and the PDF have what you have saved.">
                    Build again
                  </Button>
                  <ExcelButton businessId={businessId} instanceId={instanceId} />
                  <PdfButton key={`${ws.outward?.version ?? 0}-${ws.entries_seq ?? 0}`} businessId={businessId} instanceId={instanceId} />
                </>
              )}
              <Link className="btn btn-secondary btn-sm" to={`/b/${businessId}/filing/${instanceId}/portal-guide-3b`}>
                How to enter this on the GST portal
              </Link>
            </>
          }
        />
        {q.isPending && <Loading query={q} />}
        {q.isError && q.error.status !== 404 && <Banner tone="error">We couldn't load the worksheet. {errorText(q.error)}</Banner>}
        {ws && !ws.available && (
          <Panel title="Your worksheet">
            <p className="pad">Your worksheet is here, but its figures are not available on your plan yet.</p>
          </Panel>
        )}
        {ws?.available && (
          <>
            {ws.out_of_date && <Banner tone="error">Your GSTR-1 has changed since this worksheet was built. Build it again to see the new figures. What you entered is kept.</Banner>}
            {ws.build_blocked_by && <Banner>{ws.build_blocked_by}</Banner>}
            {build.isError && <Banner tone="error">{errorText(build.error)}</Banner>}
            {!ws.built && (
              <div className="toolbar">
                <Button disabled={!ws.can_build} busy={build.isPending} onClick={() => build.mutate()}>
                  Build the worksheet
                </Button>
                <span className="hint">The outward supplies have not been built yet.</span>
              </div>
            )}
            <WorksheetForm businessId={businessId} instanceId={instanceId} ws={ws} tab={tab} onTab={setTab} />
          </>
        )}
      </main>
    </>
  );
}
