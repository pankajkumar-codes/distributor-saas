import type { ReactNode } from "react";
import { Link, useLocation, useParams } from "react-router-dom";

import type { components } from "../../api/schema";
import { formatRupees as rupees } from "../../format/money";

type Computation = components["schemas"]["ComputationOut"];
type Issue = components["schemas"]["IssueOut"];

// Display only: every figure is the server's string; the page does no tax arithmetic.

function Issues({ title, items, tone, canLeave, productOf, hsnFix }: { title: string; items: Issue[]; tone: "error" | "info"; canLeave: boolean; productOf?: (line: number) => string | undefined; hsnFix?: (line: number, productId: string) => ReactNode }) {
  const { businessId = "" } = useParams();
  const here = useLocation().pathname;
  if (items.length === 0) return null;
  return (
    <div className={`banner banner-${tone}`} role={tone === "error" ? "alert" : "status"}>
      <strong>{title}</strong>
      <ul>
        {items.map((i, n) => (
          <li key={`${i.code}-${i.line_no ?? ""}-${n}`}>
            {i.line_no ? `Line ${i.line_no}: ` : ""}
            {i.fix}
            {i.code === "business_not_ready" && (
              <>
                {" "}
                {canLeave ? (
                  <>
                    <Link to={`/b/${businessId}/settings`} state={{ backTo: here }}>
                      Open Business setup
                    </Link>{" "}
                    (you'll come back to this invoice).
                  </>
                ) : (
                  "Save your changes first, then you can open Business setup."
                )}
              </>
            )}
            {(i.code === "hsn_missing" || i.code === "hsn_too_short") && i.line_no && productOf?.(i.line_no) && (
              <>
                {" "}
                {canLeave ? (
                  <>
                    <Link to={`/b/${businessId}/products/${productOf(i.line_no)}`} state={{ backTo: here }}>
                      Open the product
                    </Link>{" "}
                    (you'll come back to this invoice).
                  </>
                ) : (
                  "Save your changes first, then you can open the product."
                )}
              </>
            )}
            {(i.code === "hsn_missing" || i.code === "hsn_too_short") && i.line_no && productOf?.(i.line_no) && canLeave && hsnFix?.(i.line_no, productOf(i.line_no) as string)}
            {i.code === "hsn_needs_turnover_band" && (
              <>
                {" "}
                {canLeave ? (
                  <>
                    <Link to={`/b/${businessId}/settings#last-year-band`} state={{ backTo: here }}>
                      Set last year's turnover band
                    </Link>{" "}
                    (you'll come back to this invoice).
                  </>
                ) : (
                  "Save your changes first, then you can set last year's turnover band."
                )}
              </>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** What the draft would be, as of its last save (the save response's computation). */
export function Totals({ c, states, canLeave = true, productOf, hsnFix }: { c: Computation; states: Record<string, string>; canLeave?: boolean; productOf?: (line: number) => string | undefined; hsnFix?: (line: number, productId: string) => ReactNode }) {
  const heads: [string, string][] = c.is_inter_state
    ? [["IGST", c.igst_total]]
    : [["CGST", c.cgst_total], [c.utgst ? "UTGST" : "SGST", c.sgst_total]]; // fmt: skip
  return (
    <section aria-label="Totals">
      <Issues title="Fix before finalizing" items={c.blocks} tone="error" canLeave={canLeave} productOf={productOf} hsnFix={hsnFix} />
      <Issues title="Please check" items={c.warnings} tone="info" canLeave={canLeave} />
      {c.pos_state_code && (
        <p>
          Place of supply: {c.pos_state_code} {states[c.pos_state_code] ?? ""} · {c.is_inter_state ? "IGST" : c.utgst ? "CGST + UTGST" : "CGST + SGST"}
        </p>
      )}
      <dl className="totals">
        <div className="row">
          <dt>Taxable value</dt>
          <dd>{rupees(c.taxable_total)}</dd>
        </div>
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
