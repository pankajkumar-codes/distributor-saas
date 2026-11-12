import type { components } from "../../api/schema";
import { formatRupees as rupees } from "../../format/money";

type Computation = components["schemas"]["ComputationOut"];
type Issue = components["schemas"]["IssueOut"];

// Display only: every figure is the server's string; the page does no tax arithmetic.

function Issues({ title, items, tone }: { title: string; items: Issue[]; tone: "error" | "info" }) {
  if (items.length === 0) return null;
  return (
    <div className={`banner banner-${tone}`} role={tone === "error" ? "alert" : "status"}>
      <strong>{title}</strong>
      <ul>
        {items.map((i, n) => (
          <li key={`${i.code}-${i.line_no ?? ""}-${n}`}>
            {i.line_no ? `Line ${i.line_no}: ` : ""}
            {i.fix}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** What the draft would be, as of its last save (the save response's computation). */
export function Totals({ c, states }: { c: Computation; states: Record<string, string> }) {
  const heads: [string, string][] = c.is_inter_state
    ? [["IGST", c.igst_total]]
    : [["CGST", c.cgst_total], [c.utgst ? "UTGST" : "SGST", c.sgst_total]]; // fmt: skip
  return (
    <section aria-label="Totals">
      <Issues title="Fix before finalizing" items={c.blocks} tone="error" />
      <Issues title="Please check" items={c.warnings} tone="info" />
      {c.pos_state_code && (
        <p>
          Place of supply: {c.pos_state_code} {states[c.pos_state_code] ?? ""} · {c.is_inter_state ? "IGST" : c.utgst ? "CGST + UTGST" : "CGST + SGST"}
        </p>
      )}
      <dl className="totals">
        <dt>Taxable value</dt>
        <dd>{rupees(c.taxable_total)}</dd>
        {heads.map(([name, v]) => (
          <div key={name} className="row">
            <dt>{name}</dt>
            <dd>{rupees(v)}</dd>
          </div>
        ))}
        {/[1-9]/.test(c.round_off) && (
          <div className="row">
            <dt>Round off</dt>
            <dd>{rupees(c.round_off)}</dd>
          </div>
        )}
        <div className="row total">
          <dt>Total</dt>
          <dd>{rupees(c.doc_total)}</dd>
        </div>
      </dl>
      <p className="hint">{c.amount_in_words}</p>
    </section>
  );
}
