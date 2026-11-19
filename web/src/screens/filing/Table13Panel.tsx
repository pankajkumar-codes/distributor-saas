import { useState } from "react";

import { errorText } from "../../api/errors";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { NATURES, problem, toBody, toDraft, useConfirmTable13, useTable13, type Draft, type Table13 } from "./table13";

const SOURCE: Record<string, string> = { own_live: "Your invoices here", uploaded_own: "Your uploaded invoices", marketplace: "Marketplace", manual: "Added by you" };

function Rows({ businessId, instanceId, data }: { businessId: string; instanceId: string; data: Table13 }) {
  const initial = data.rows.map(toDraft);
  const [rows, setRows] = useState<Draft[]>(initial);
  const [next, setNext] = useState(initial.length);
  const confirm = useConfirmTable13(businessId, instanceId);
  const edit = (key: number, patch: Partial<Draft>) => setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  const problems = rows.map(problem);
  const bad = problems.find((p) => p !== null) ?? null;
  const unchanged = JSON.stringify(rows.map(toBody)) === JSON.stringify(initial.map(toBody));
  const counted = rows.filter((r) => r.counted).length;
  const standing = data.confirmed && unchanged;

  return (
    <div className="stack">
      {data.stale && <Banner tone="error">The documents in this period have changed since you confirmed these rows. Check them and confirm again.</Banner>}
      {data.required && !standing && counted === 0 && <Banner tone="error">The GST portal will not let you generate the summary until at least one series below is counted. Tick a series, or add your own.</Banner>}
      {rows.length === 0 && <p>We found no invoice series in this period. Add the series you issued, with its first and last number.</p>}
      {rows.length > 0 && (
        <div className="tablewrap">
          <table className="products">
            <thead>
              <tr>
                <th scope="col">Kind of document</th>
                <th scope="col">From</th>
                <th scope="col">To</th>
                <th scope="col">Total issued</th>
                <th scope="col">Cancelled</th>
                <th scope="col">Net issued</th>
                <th scope="col">Count it</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => {
                const name = `${r.label} ${r.from_no || "new series"}`;
                const net = COUNT_OK(r) ? String(Number(r.total) - Number(r.cancelled)) : "—";
                return (
                  <tr key={r.key}>
                    <td data-label="Kind of document">
                      {r.manual ? (
                        <select aria-label={`Kind of document, row ${i + 1}`} value={r.nature} onChange={(e) => edit(r.key, { nature: Number(e.target.value), label: NATURES.find((n) => n.value === Number(e.target.value))?.label ?? r.label })}>
                          {NATURES.map((n) => (
                            <option key={n.value} value={n.value}>
                              {n.label}
                            </option>
                          ))}
                        </select>
                      ) : (
                        r.label
                      )}
                      <div>
                        <span className="chip">{SOURCE[r.source] ?? r.source}</span>
                        {r.ca && <span className="chip chip-warn">Needs CA check</span>}
                      </div>
                      {r.missing > 0 && <p className="hint">{r.missing === 1 ? "1 number in this range is" : `${r.missing} numbers in this range are`} not in your files. Enter them as cancelled, or lower the total.</p>}
                      {problems[i] && <p className="error" role="alert">{problems[i]}</p>}
                    </td>
                    <td data-label="From">
                      {r.manual ? <input aria-label={`From, ${name}`} value={r.from_no} maxLength={16} onChange={(e) => edit(r.key, { from_no: e.target.value })} /> : r.from_no}
                    </td>
                    <td data-label="To">{r.manual ? <input aria-label={`To, ${name}`} value={r.to_no} maxLength={16} onChange={(e) => edit(r.key, { to_no: e.target.value })} /> : r.to_no}</td>
                    <td data-label="Total issued">
                      <input aria-label={`Total issued, ${name}`} inputMode="numeric" value={r.total} onChange={(e) => edit(r.key, { total: e.target.value })} />
                    </td>
                    <td data-label="Cancelled">
                      <input aria-label={`Cancelled, ${name}`} inputMode="numeric" value={r.cancelled} onChange={(e) => edit(r.key, { cancelled: e.target.value })} />
                    </td>
                    <td data-label="Net issued">{net}</td>
                    <td data-label="Count it">
                      <label>
                        <input type="checkbox" aria-label={`Count ${name}`} checked={r.counted} onChange={(e) => edit(r.key, { counted: e.target.checked })} /> Count
                      </label>
                      {r.manual && (
                        <Button variant="secondary" onClick={() => setRows((rs) => rs.filter((x) => x.key !== r.key))}>
                          Remove
                        </Button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <Button
        variant="secondary"
        onClick={() => {
          setRows((rs) => [...rs, { key: next, nature: 1, from_no: "", to_no: "", total: "0", cancelled: "0", counted: true, manual: true, source: "manual", label: NATURES[0].label, missing: 0, ca: false }]);
          setNext(next + 1);
        }}
      >
        Add a series
      </Button>
      <p className="hint">Marketplace series are off until you count them. Whether they belong in your own list is a question for your CA.</p>
      {confirm.isError && <Banner tone="error">{errorText(confirm.error)}</Banner>}
      {standing ? (
        <p>
          <span className="chip chip-ok">Confirmed</span> Version {data.version}. Change a row to confirm again.
        </p>
      ) : (
        <Button busy={confirm.isPending} disabled={bad !== null || rows.length === 0} onClick={() => confirm.mutate(rows.map(toBody))}>
          Confirm these rows
        </Button>
      )}
    </div>
  );
}

const COUNT_OK = (r: Draft) => /^\d{1,8}$/.test(r.total) && /^\d{1,8}$/.test(r.cancelled) && Number(r.cancelled) <= Number(r.total);

/**
 * Documents issued (Table 13), the step before the GSTR-1 file. The server finds the series in the return's own invoices;
 * the person types the cancelled count, may add series by hand, and confirms. Check C-08 stays on until they do, and again
 * when the documents change after. Docs/TABLE13_SPEC.md section 5; mocks v15 have no such screen, so this follows the kit.
 */
export function Table13Panel({ businessId, instanceId }: { businessId: string; instanceId: string }) {
  const t = useTable13(businessId, instanceId, true);
  if (t.isPending) return <p aria-busy="true">Loading documents issued…</p>;
  if (t.isError) return <Banner tone="error">We couldn't load the documents issued. {errorText(t.error)}</Banner>;
  if (!t.data.applies) return null;
  return (
    <section className="card" aria-labelledby="table13">
      <h2 id="table13">Documents issued (Table 13)</h2>
      <p className="hint">The GST portal wants the first and last number of every series of invoices and credit notes issued in this period. We found these in your invoices. Check them, then confirm.</p>
      {!t.data.required && t.data.rows.length === 0 && <p>This return has no sales yet, so the portal does not ask for this.</p>}
      <Rows key={`${t.data.fingerprint}-${t.data.version ?? 0}`} businessId={businessId} instanceId={instanceId} data={t.data} />
    </section>
  );
}
