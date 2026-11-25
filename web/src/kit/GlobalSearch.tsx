import { useQuery } from "@tanstack/react-query";
import { useId, useState } from "react";
import { Link } from "react-router-dom";

import { api, call } from "../api/client";
import { formatRupees } from "../format/money";
import { useDebounced } from "./useDebounced";

const LIMIT = 5;

/**
 * The top bar's search (mocks v16: always visible, no shortcut key). Nothing is suggested:
 * results appear only once a letter is typed, from the server's own invoice, customer and
 * product searches for this business. The server scopes each to the signed-in member's
 * business; issued invoices are asked for only by a role that may see them (`invoices`).
 */
export function GlobalSearch({ businessId, invoices = false }: { businessId: string; invoices?: boolean }) {
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const q = useDebounced(text.trim(), 250);
  const on = q.length > 0;
  const listId = useId();

  const documents = useQuery({
    queryKey: ["b", businessId, "search", "documents", q],
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/documents", { params: { path: { business_id: businessId }, query: { q, limit: LIMIT, offset: 0 } } })),
    enabled: on && invoices,
    retry: false,
    staleTime: 30_000,
  });
  const customers = useQuery({
    queryKey: ["b", businessId, "search", "customers", q],
    queryFn: () =>
      call(() =>
        api.GET("/api/v1/b/{business_id}/customers", { params: { path: { business_id: businessId }, query: { q, status: "active", limit: LIMIT, offset: 0 } } }),
      ),
    enabled: on,
    retry: false,
    staleTime: 30_000,
  });
  const products = useQuery({
    queryKey: ["b", businessId, "search", "products", q],
    queryFn: () =>
      call(() =>
        api.GET("/api/v1/b/{business_id}/products", { params: { path: { business_id: businessId }, query: { q, status: "active", limit: LIMIT, offset: 0 } } }),
      ),
    enabled: on,
    retry: false,
    staleTime: 30_000,
  });

  const ds = (invoices && documents.data?.documents) || [];
  const cs = customers.data?.items ?? [];
  const ps = products.data?.items ?? [];
  const found = ds.length + cs.length + ps.length;
  const busy = on && ((invoices && documents.isFetching) || customers.isFetching || products.isFetching);
  const close = () => {
    setOpen(false);
    setText("");
  };

  return (
    <div className="search" role="search" onBlur={(e) => !e.currentTarget.contains(e.relatedTarget) && setOpen(false)}>
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="11" cy="11" r="6.5" />
        <path d="M16 16l4 4" />
      </svg>
      <input
        type="text"
        role="combobox"
        aria-autocomplete="list"
        aria-label={invoices ? "Search invoices, customers and products" : "Search customers and products"}
        placeholder={invoices ? "Search invoices, customers, products" : "Search customers, products"}
        value={text}
        autoComplete="off"
        aria-controls={listId}
        aria-expanded={open && on}
        onChange={(e) => {
          setText(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => e.key === "Escape" && close()}
      />
      {open && on && (
        <div className="search-pop" id={listId}>
          {busy && found === 0 && <p className="hint">Searching…</p>}
          {!busy && found === 0 && <p className="hint">Nothing matches “{q}”.</p>}
          {ds.length > 0 && (
            <section aria-label="Invoices">
              <div className="grp">Invoices</div>
              {ds.map((d) => (
                <Link key={d.id} to={`/b/${businessId}/documents/${d.id}`} onClick={close}>
                  <span>
                    <span className="num">{d.doc_number}</span> {d.counterparty_name ?? ""}
                  </span>
                  <span className="num sub2">{formatRupees(d.doc_total)}</span>
                </Link>
              ))}
            </section>
          )}
          {cs.length > 0 && (
            <section aria-label="Customers">
              <div className="grp">Customers</div>
              {cs.map((c) => (
                <Link key={c.id} to={`/b/${businessId}/customers/${c.id}`} onClick={close}>
                  {c.name}
                  {c.gstin && <span className="num sub2">{c.gstin}</span>}
                </Link>
              ))}
            </section>
          )}
          {ps.length > 0 && (
            <section aria-label="Products">
              <div className="grp">Products</div>
              {ps.map((p) => (
                <Link key={p.id} to={`/b/${businessId}/products/${p.id}`} onClick={close}>
                  {p.name}
                  {p.code && <span className="num sub2">{p.code}</span>}
                </Link>
              ))}
            </section>
          )}
        </div>
      )}
    </div>
  );
}
