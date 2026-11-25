import { useId, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";

import { formatRupees } from "../../format/money";
import "./filing.css";

/**
 * Shared parts of the GST filing screens in the Ledger look (mocks v16, #399): the page head (a grey trail, the
 * title, one line on what to do, actions on the right) and a panel with its own header row. The screens' <main>
 * carries the `ledger` class that filing.css hangs off.
 */
export function LedgerHead({ trail, title, lead, actions }: { trail: ReactNode; title: ReactNode; lead?: ReactNode; actions?: ReactNode }) {
  return (
    <>
      <div className="eyebrow">{trail}</div>
      <div className="head">
        <h1>{title}</h1>
        {actions && <div className="actions-r">{actions}</div>}
      </div>
      {lead && <p className="lead">{lead}</p>}
    </>
  );
}

export function Panel({ title, aside, children, className }: { title: ReactNode; aside?: ReactNode; children: ReactNode; className?: string }) {
  const id = useId();
  return (
    <section className={`panel ${className ?? ""}`.trim()} aria-labelledby={id}>
      <div className="panel-h">
        <h2 id={id}>{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

/** The return code in grey beside a plain name (mocks v16: plain names first). */
export function Code({ children }: { children: ReactNode }) {
  return <span className="code">{children}</span>;
}

/** An amount, or "—" when it is nil or missing (mocks v16: never ₹0.00 for an empty amount). From the string alone. */
export function amountOrDash(amount: string | null | undefined): string {
  if (amount === null || amount === undefined || amount.trim() === "") return "—";
  if (/^\s*-?0*(\.0*)?\s*$/.test(amount)) return "—";
  return formatRupees(amount);
}

/** Which tab is open, kept in the address as ?tab=<key> so a reload or a shared link opens the same tab. */
export function useTab(keys: string[], fallback = 0): [number, (i: number) => void] {
  const [params, setParams] = useSearchParams();
  const at = keys.indexOf(params.get("tab") ?? "");
  const set = (i: number) =>
    setParams(
      (p) => {
        const next = new URLSearchParams(p);
        next.set("tab", keys[i]);
        return next;
      },
      { replace: true },
    );
  return [at >= 0 ? at : Math.min(fallback, keys.length - 1), set];
}
