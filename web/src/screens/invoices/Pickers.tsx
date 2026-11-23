import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { useDebounced } from "../../kit/useDebounced";

type Customer = components["schemas"]["CustomerOut"];
type Product = components["schemas"]["ProductOut"];

type Props<T> = {
  businessId: string;
  label: string;
  hint?: string;
  error?: string;
  onPick: (item: T) => void;
};

/** A search box over a list route; picking a result calls onPick and clears the box. */
function Picker<T extends { id: string }>({ label, hint, error, onPick, kind, businessId, show, fetchItems }: Props<T> & {
  kind: "customers" | "products";
  show: (i: T) => string;
  fetchItems: (q: string) => Promise<{ items: T[] }>;
}) {
  const [text, setText] = useState("");
  const q = useDebounced(text.trim());
  const found = useQuery<{ items: T[] }, ApiError>({
    queryKey: ["b", businessId, "picker", kind, q],
    enabled: q.length > 0,
    queryFn: () => fetchItems(q),
  });
  const id = `picker-${kind}`;
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input id={id} type="search" autoComplete="off" value={text} onChange={(e) => setText(e.target.value)} aria-invalid={error ? true : undefined} />
      {hint && <p className="hint">{hint}</p>}
      {error && <p className="error">{error}</p>}
      {found.error && <p className="error">{errorText(found.error)}</p>}
      {q && found.isSuccess && found.data.items.length === 0 && <p className="hint">No match.</p>}
      {found.data && found.data.items.length > 0 && (
        <ul className="picker" aria-label={`${label} results`}>
          {found.data.items.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                className="btn btn-link"
                onClick={() => {
                  onPick(item);
                  setText("");
                }}
              >
                {show(item)}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const query = (q: string) => ({ status: "active" as const, q, limit: 8 });

export const CustomerPicker = (p: Props<Customer>) => (
  <Picker<Customer>
    {...p}
    kind="customers"
    show={(c) => (c.gstin ? `${c.name} · ${c.gstin}` : c.name)}
    fetchItems={(q) => call(() => api.GET("/api/v1/b/{business_id}/customers", { params: { path: { business_id: p.businessId }, query: query(q) } }))}
  />
);
export const ProductPicker = (p: Props<Product>) => (
  <Picker<Product>
    {...p}
    kind="products"
    show={(x) => (x.hsn ? `${x.name} · HSN ${x.hsn}` : x.name)}
    fetchItems={(q) => call(() => api.GET("/api/v1/b/{business_id}/products", { params: { path: { business_id: p.businessId }, query: query(q) } }))}
  />
);

type Address = Customer["billing"];
const addressText = (a: Address | null | undefined, stateNames: Record<string, string>) =>
  a ? [a.line1, a.line2, a.city, a.pin, a.state_code && `${stateNames[a.state_code] ?? ""} (${a.state_code})`.trim()].filter(Boolean).join(", ") : "";

/**
 * The customer on the invoice: name, GSTIN and billing address, with Change to pick another. The details come from the
 * customer record (already in the cache after a pick; read once when a saved draft is opened). If that read fails, the
 * name alone is shown, which is what the draft itself stores.
 */
export function ChosenCustomer({ businessId, customerId, name, stateNames, onChange }: {
  businessId: string;
  customerId: string;
  name: string;
  stateNames: Record<string, string>;
  onChange: () => void;
}) {
  const found = useQuery<Customer, ApiError>({
    queryKey: ["b", businessId, "customer", customerId],
    staleTime: 5 * 60_000,
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/customers/{customer_id}", { params: { path: { business_id: businessId, customer_id: customerId } } })),
  });
  const c = found.data;
  const billing = addressText(c?.billing, stateNames);
  const delivery = c && !c.delivery_same_as_billing ? addressText(c.delivery, stateNames) : "";
  return (
    <section className="card" aria-label="Customer">
      <div className="card-head">
        <p>
          Customer: <strong>{c?.name ?? name}</strong>
        </p>
        <button type="button" className="btn btn-link" onClick={onChange}>
          Change
        </button>
      </div>
      {c && <p>{c.gstin ? `GSTIN ${c.gstin}` : "No GSTIN (unregistered)"}</p>}
      {billing && <p>Billing address: {billing}</p>}
      {delivery && <p>Delivers to: {delivery}</p>}
    </section>
  );
}
