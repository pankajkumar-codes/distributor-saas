import type { ReactNode } from "react";
import { Link } from "react-router-dom";

export type Crumb = { label: string; to?: string };

/**
 * The head of a v16 screen: a breadcrumb ("Sell / Products / …"), the title with an optional
 * grey count, an optional line under it, and the screen's buttons on the right.
 */
export function PageHead({ crumbs, title, count, sub, children }: { crumbs: Crumb[]; title: ReactNode; count?: number; sub?: ReactNode; children?: ReactNode }) {
  return (
    <>
      <nav className="eyebrow" aria-label="Breadcrumb">
        {crumbs.map((c, i) => (
          <span key={i}>
            {i > 0 && <span aria-hidden="true">/ </span>}
            {c.to ? <Link to={c.to}>{c.label}</Link> : <span aria-current={i === crumbs.length - 1 ? "page" : undefined}>{c.label}</span>}
          </span>
        ))}
      </nav>
      <div className="ph">
        <div>
          <h1>
            {title}
            {count !== undefined && <span className="count">{count}</span>}
          </h1>
          {sub && <p className="ph-sub">{sub}</p>}
        </div>
        {children && <div className="row-actions">{children}</div>}
      </div>
    </>
  );
}

/** The search box in a list's toolbar (mocks v16): a magnifier, the label kept for screen readers. */
export function SearchBox({ id, label, value, onChange }: { id: string; label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div className="search">
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="11" cy="11" r="7" />
        <path d="m20 20-3.5-3.5" />
      </svg>
      <label htmlFor={id} className="visually-hidden">
        {label}
      </label>
      <input id={id} type="search" placeholder={label} value={value} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}
