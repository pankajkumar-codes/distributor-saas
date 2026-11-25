import type { ReactNode } from "react";
import { Link, useLocation, useParams } from "react-router-dom";

import type { components } from "../../api/schema";
import { formatDate } from "../../format/dates";
import { formatRupees as rupees } from "../../format/money";

type Computation = components["schemas"]["ComputationOut"];
export type Issue = components["schemas"]["IssueOut"];

// The checks that offer the inline HSN box: the blocks, and the warnings for a buyer without a GSTIN (#344, #367), where adding
// the HSN is optional now but the GSTR-1 return will need it.
const HSN_FIX_CODES = ["hsn_missing", "hsn_too_short", "hsn_missing_b2c", "hsn_short_b2c"];

// Display only: every figure is the server's string; the page does no tax arithmetic.

type IssueProps = { canLeave: boolean; productId?: string; hsnFix?: (line: number, productId: string) => ReactNode };

/** One check from the server, in its words, with the way to fix it where there is one. */
export function IssueText({ issue: i, canLeave, productId, hsnFix }: IssueProps & { issue: Issue }) {
  const { businessId = "" } = useParams();
  const here = useLocation().pathname;
  const leave = (to: string, words: string, later: string) =>
    canLeave ? (
      <>
        {" "}
        <Link to={to} state={{ backTo: here }}>
          {words}
        </Link>{" "}
        (you'll come back to this invoice).
      </>
    ) : (
      ` Save your changes first, then you can ${later}.`
    );
  return (
    <>
      {i.fix}
      {i.code === "business_not_ready" && leave(`/b/${businessId}/settings`, "Open Business setup", "open Business setup")}
      {(i.code === "hsn_missing" || i.code === "hsn_too_short") && productId && leave(`/b/${businessId}/products/${productId}`, "Open the product", "open the product")}
      {HSN_FIX_CODES.includes(i.code) && i.line_no && productId && canLeave && hsnFix?.(i.line_no, productId)}
      {i.code === "hsn_needs_turnover_band" && leave(`/b/${businessId}/settings#last-year-band`, "Set last year's turnover band", "set last year's turnover band")}
    </>
  );
}

/** A list of checks (the ones not about one line), each with its fix. */
export function Issues({ title, items, tone, canLeave }: { title: string; items: Issue[]; tone: "error" | "info"; canLeave: boolean }) {
  if (items.length === 0) return null;
  return (
    <div className={`banner banner-${tone} issues`} role={tone === "error" ? "alert" : "status"}>
      <strong>{title}</strong>
      <ul>
        {items.map((i, n) => (
          <li key={`${i.code}-${n}`}>
            <IssueText issue={i} canLeave={canLeave} />
          </li>
        ))}
      </ul>
    </div>
  );
}

export type PaperLine = { key: string; name: string; detail: string; quantity: string; amount: string | null };

const CAP = 3; // lines drawn on the paper; the rest are counted (mocks v16)

/**
 * The live invoice paper on the right of New invoice (mocks v16): who it is from and to, the first
 * lines and the totals. Figures are the server's computation of the last save; before the first
 * save, or for a line changed since, they show "—".
 */
export function Paper({ c, from, to, lines, date, practice, states, stale }: {
  c: Computation | null | undefined;
  from: { name: string; gstin: string | null };
  to: ReactNode;
  lines: PaperLine[];
  date: string;
  practice: boolean;
  states: Record<string, string>;
  stale: boolean;
}) {
  const money = (v: string | null | undefined) => (c && v != null && !stale ? rupees(v) : "—");
  const heads: [string, string][] = !c
    ? [["CGST", ""], ["SGST", ""]]
    : c.is_inter_state
      ? [["IGST", c.igst_total]]
      : [["CGST", c.cgst_total], [c.utgst ? "UTGST" : "SGST", c.sgst_total]]; // fmt: skip
  const discounts = c && /[1-9]/.test(c.line_discount_total) ? c.line_discount_total : null;
  return (
    <section className="paper" aria-label="Invoice preview">
      <div className="ph">
        <div>
          <div className="ttl">Tax invoice</div>
          <div className="num sub2">Number on create · {formatDate(date)}</div>
        </div>
        {practice && <span className="stamp">PRACTICE</span>}
      </div>
      <div className="two">
        <div>
          <span className="k">From</span>
          <b>{from.name}</b>
          {from.gstin && (
            <>
              <br />
              <span className="num">{from.gstin}</span>
            </>
          )}
        </div>
        <div>
          <span className="k">Bill to</span>
          {to}
        </div>
      </div>
      <table>
        <thead>
          <tr>
            <th scope="col">Item</th>
            <th scope="col" className="r">
              Qty
            </th>
            <th scope="col" className="r">
              Amount
            </th>
          </tr>
        </thead>
        <tbody>
          {lines.length === 0 && (
            <tr>
              <td colSpan={3} className="sub2">
                Items appear here as you add them
              </td>
            </tr>
          )}
          {lines.slice(0, CAP).map((l) => (
            <tr key={l.key}>
              <td>
                {l.name}
                <br />
                <span className="num sub2">{l.detail}</span>
              </td>
              <td className="r num">{l.quantity}</td>
              <td className="r num">{l.amount && !stale ? rupees(l.amount) : "—"}</td>
            </tr>
          ))}
          {lines.length > CAP && (
            <tr>
              <td colSpan={3} className="sub2">
                + {lines.length - CAP} more {lines.length - CAP === 1 ? "item" : "items"} on the PDF
              </td>
            </tr>
          )}
        </tbody>
      </table>
      <div className="tot num">
        {discounts && (
          <div>
            <span>Discounts given</span>
            <span>{money(discounts)}</span>
          </div>
        )}
        <div>
          <span>Taxable value</span>
          <span>{money(c?.taxable_total)}</span>
        </div>
        {heads.map(([name, v]) => (
          <div key={name}>
            <span>{name}</span>
            <span>{c ? money(v) : "—"}</span>
          </div>
        ))}
        {c && /[1-9]/.test(c.round_off) && (
          <div>
            <span>Round off</span>
            <span>{money(c.round_off)}</span>
          </div>
        )}
        <div className="grand">
          <span>Total</span>
          <span>{money(c?.doc_total)}</span>
        </div>
      </div>
      <p className="words">
        Place of supply: {c?.pos_state_code ? `${states[c.pos_state_code] ?? ""} (${c.pos_state_code})`.trim() : "—"}
        {c && !stale && c.amount_in_words ? ` · ${c.amount_in_words}` : ""}
      </p>
    </section>
  );
}
