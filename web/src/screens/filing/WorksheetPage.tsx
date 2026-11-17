import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { errorText, type ApiError } from "../../api/errors";
import { canPrepareReturns } from "../../auth/roles";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { formatRupees } from "../../format/money";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { Field } from "../../kit/Field";
import { NotFound } from "../../kit/NotFound";
import { TopBar } from "../../kit/TopBar";
import { useBuildWorksheet, useSaveEntries, useWorksheetExcel, useWorksheet, type Outward, type Worksheet } from "./worksheet";
import { HEAD_NAME, TABLES, typedHeads } from "./worksheetRows";

const TAX_HEADS = ["igst", "cgst", "sgst", "cess"] as const;
const NOT_BUILT = "Not built from your uploads yet. Check it on the GST portal.";

function OutwardCard({ o }: { o: Outward }) {
  return (
    <>
      <section className="card" aria-labelledby="ws-31">
        <h2 id="ws-31">3.1 Outward supplies, from your invoices</h2>
        <p className="hint">Build {o.version}, made {new Date(o.built_at).toLocaleString("en-IN")}.</p>
        <h3>(a) Outward taxable supplies (other than zero rated, nil rated and exempted)</h3>
        <dl className="totals">
          <div className="row">
            <dt>Taxable value</dt>
            <dd>{formatRupees(o.taxable.taxable_value)}</dd>
          </div>
          <div className="row">
            <dt>Integrated Tax</dt>
            <dd>{formatRupees(o.taxable.igst)}</dd>
          </div>
          <div className="row">
            <dt>Central Tax</dt>
            <dd>{formatRupees(o.taxable.cgst)}</dd>
          </div>
          <div className="row">
            <dt>State/UT Tax</dt>
            <dd>{formatRupees(o.taxable.sgst)}</dd>
          </div>
          <div className="row">
            <dt>Cess</dt>
            <dd>{formatRupees(o.taxable.cess)}</dd>
          </div>
        </dl>
        <p className="hint">Made from {o.taxable_refs.length} source {o.taxable_refs.length === 1 ? "row" : "rows"}.</p>
        <h3>(b) Zero rated, (c) nil rated or exempted, (e) non-GST</h3>
        <p>{NOT_BUILT}</p>
        <h3>(d) Inward supplies liable to reverse charge</h3>
        <p>Type it in the section below. We do not work it out.</p>
        <p>3.1.1 Supplies notified under section 9(5): check on the GST portal.</p>
      </section>
      <section className="card" aria-labelledby="ws-32">
        <h2 id="ws-32">3.2 Inter-state supplies to unregistered buyers</h2>
        {o.inter_state.length === 0 ? (
          <p>No inter-state supplies to unregistered buyers in this period.</p>
        ) : (
          <table className="products">
            <thead>
              <tr>
                <th scope="col">Place of supply</th>
                <th scope="col">Taxable value</th>
                <th scope="col">Integrated Tax</th>
              </tr>
            </thead>
            <tbody>
              {o.inter_state.map((r) => (
                <tr key={r.pos_state_code}>
                  <td>State code {r.pos_state_code}</td>
                  <td>{formatRupees(r.unregistered_taxable)}</td>
                  <td>{formatRupees(r.unregistered_igst)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p>
          Total: {formatRupees(o.inter_state_taxable)} taxable value, {formatRupees(o.inter_state_igst)} Integrated Tax.
        </p>
      </section>
      {o.flags.length > 0 && (
        <section className="card" aria-labelledby="ws-flags">
          <h2 id="ws-flags">Please check these ({o.flags.length})</h2>
          <ul>
            {o.flags.map((f) => (
              <li key={f.code}>{f.text}</li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}

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
    <div>
      <Button
        variant="secondary"
        busy={excel.isPending}
        onClick={() => excel.mutate(undefined, { onSuccess: (r) => window.location.assign(r.url) })}
      >
        Download as Excel
      </Button>
      <span className="hint"> The file has what you have saved, not boxes you are still typing in.</span>
      {excel.isError && <Banner tone="error">{errorText(excel.error)}</Banner>}
    </div>
  );
}

/** What the seller types. The boxes keep what was typed, also when someone else has saved in the meantime. */
function EntriesForm({ businessId, instanceId, ws }: { businessId: string; instanceId: string; ws: Worksheet }) {
  const save = useSaveEntries(businessId, instanceId);
  const [values, setValues] = useState<Record<string, string>>(() => typedOnly(ws.entries));
  const [saved, setSaved] = useState(false);
  // The save these boxes were last in step with. A second save from an old one is refused by the server, so a stale
  // form can never overwrite what someone else saved without the person choosing to see it first.
  const [baseSeq, setBaseSeq] = useState<number | null>(ws.entries_seq);
  const err: ApiError | null = save.error;
  const set = (name: string, v: string) => {
    setSaved(false);
    setValues((cur) => ({ ...cur, [name]: v }));
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
  return (
    <form onSubmit={submit} noValidate aria-label="What you enter yourself">
      <section className="card">
        <h2>What you enter yourself</h2>
        <p className="hint">Everything in this section is typed by you. We keep it and show it back, and do not check it against the GST rules. Leave a box empty if it is nil.</p>
      </section>
      {TABLES.map((t) => (
        <section className="card" key={t.id} aria-labelledby={`ws-${t.id}`}>
          <h2 id={`ws-${t.id}`}>{t.title}</h2>
          {t.hint && <p className="hint">{t.hint}</p>}
          {t.rows.map((r) => (
            <fieldset key={r.key} className="line">
              <legend>{r.label}</legend>
              <div className="grid2">
                {typedHeads(r).map((h) => {
                  const name = `${t.id}.${r.key}.${h}`;
                  return (
                    <Field
                      key={h}
                      label={h === "cgst" && r.copy ? "Central Tax (State/UT Tax is the same)" : HEAD_NAME[h]}
                      inputMode="decimal"
                      autoComplete="off"
                      value={values[name] ?? ""}
                      onChange={(e) => set(name, e.target.value)}
                      error={err?.field === name || (r.copy && h === "cgst" && err?.field === `${t.id}.${r.key}.sgst`) ? err.fix ?? err.message : undefined}
                    />
                  );
                })}
              </div>
            </fieldset>
          ))}
        </section>
      ))}
      {Object.keys(ws.net_itc).length > 0 && (
        <section className="card" aria-labelledby="ws-net">
          <h2 id="ws-net">4(C) Net ITC, from what you typed</h2>
          <p className="hint">Available minus reversed, as saved. Shown for your reference only.</p>
          <dl className="totals">
            {TAX_HEADS.map((h) => (
              <div className="row" key={h}>
                <dt>{HEAD_NAME[h]}</dt>
                <dd>{formatRupees(ws.net_itc[h] ?? "0")}</dd>
              </div>
            ))}
          </dl>
        </section>
      )}
      {stale && (
        <Banner tone="error">
          <p>Your changes were not saved. Someone else saved this worksheet while you were typing. Your boxes still show what you typed.</p>
          <Button type="button" variant="secondary" onClick={showSaved}>
            Show what was saved instead
          </Button>
        </Banner>
      )}
      {err && !err.field && !stale && <Banner tone="error">{errorText(err)}</Banner>}
      {err?.field && <Banner tone="error">Some amounts need a change. {errorText(err)}</Banner>}
      {saved && <Banner>Saved.</Banner>}
      <Button type="submit" busy={save.isPending}>
        Save what I entered
      </Button>
    </form>
  );
}

/** /b/:id/filing/:instanceId/worksheet (R1-M8b W4): numbers to check and enter on the GST portal. Never a filing. */
export function WorksheetPage() {
  const { businessId = "", instanceId = "" } = useParams();
  const businesses = useMyBusinesses();
  const business = businesses.data?.find((b) => b.business_id === businessId);
  const allowed = business !== undefined && canPrepareReturns(business.role);
  const q = useWorksheet(businessId, instanceId, allowed);
  const build = useBuildWorksheet(businessId, instanceId);

  if (businesses.isPending) {
    return (
      <main className="page" aria-busy="true">
        <p>Loading…</p>
      </main>
    );
  }
  if (!business || !allowed || (q.isError && q.error.status === 404)) return <NotFound />;
  const ws = q.data;

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page">
        <p className="step">
          <Link to={`/b/${businessId}/filing`}>Your GST filing</Link>
        </p>
        <h1>GSTR-3B worksheet</h1>
        {ws && (
          <>
            <p>
              <span className="chip chip-warn">{ws.label}</span>
            </p>
            <Banner>
              {ws.note} {ws.offset_note}
            </Banner>
          </>
        )}
        {q.isPending && <p aria-busy="true">Loading…</p>}
        {q.isError && q.error.status !== 404 && <Banner tone="error">We couldn't load the worksheet. {errorText(q.error)}</Banner>}
        {ws && !ws.available && (
          <section className="card">
            <p>Your worksheet is here, but its figures are not available on your plan yet.</p>
          </section>
        )}
        {ws?.available && (
          <>
            {ws.out_of_date && <Banner tone="error">Your GSTR-1 has changed since this worksheet was built. Build it again to see the new figures. What you entered is kept.</Banner>}
            {!ws.built && (
              <section className="card">
                <p>The outward supplies have not been built yet.</p>
              </section>
            )}
            {ws.build_blocked_by && <Banner>{ws.build_blocked_by}</Banner>}
            {build.isError && <Banner tone="error">{errorText(build.error)}</Banner>}
            <p>
              <Button variant={ws.built ? "secondary" : "primary"} disabled={!ws.can_build} busy={build.isPending} onClick={() => build.mutate()}>
                {ws.built ? "Build again" : "Build the worksheet"}
              </Button>
            </p>
            {ws.built && <ExcelButton businessId={businessId} instanceId={instanceId} />}
            {ws.outward && <OutwardCard o={ws.outward} />}
            <EntriesForm businessId={businessId} instanceId={instanceId} ws={ws} />
          </>
        )}
      </main>
    </>
  );
}
