import { useQuery } from "@tanstack/react-query";
import { useId, useState, type ReactNode } from "react";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { formatRupees } from "../../format/money";
import { useDebounced } from "../../kit/useDebounced";
import { gstText, hsnText } from "./lineFacts";

type Customer = components["schemas"]["CustomerOut"];
type Product = components["schemas"]["ProductOut"];

type Props<T> = {
  businessId: string;
  label: string;
  placeholder?: string;
  error?: string;
  onPick: (item: T) => void;
  /** Shown under the results when nothing matches, e.g. a link to add one. */
  none?: ReactNode;
};

/**
 * A search box over a list route (mocks v16): nothing is suggested before a letter is typed;
 * from the first letter the server's own search answers. Picking a result calls onPick and
 * clears the box. The server scopes the search to this business.
 */
function Picker<T extends { id: string }>({ label, placeholder, error, onPick, none, kind, businessId, show, fetchItems, exclude }: Props<T> & {
  kind: "customers" | "products";
  show: (i: T) => ReactNode;
  fetchItems: (q: string) => Promise<{ items: T[] }>;
  exclude?: ReadonlySet<string>;
}) {
  const [text, setText] = useState("");
  const q = useDebounced(text.trim(), 200);
  const found = useQuery<{ items: T[] }, ApiError>({
    queryKey: ["b", businessId, "picker", kind, q],
    enabled: q.length > 0,
    queryFn: () => fetchItems(q),
  });
  const id = useId();
  const items = (found.data?.items ?? []).filter((i) => !exclude?.has(i.id));
  const open = text.trim().length > 0 && q.length > 0;
  return (
    <div className="pick">
      <input
        id={id}
        className="inp"
        type="search"
        autoComplete="off"
        aria-label={label}
        placeholder={placeholder ?? label}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => e.key === "Escape" && setText("")}
        aria-invalid={error ? true : undefined}
      />
      {error && <p className="error">{error}</p>}
      {open && (found.error || found.isSuccess) && (
        <div className="results drop-res" role="region" aria-label={`${label} results`}>
          {found.error && <p className="empty error">{errorText(found.error)}</p>}
          {found.isSuccess && items.length === 0 && (
            <p className="empty">
              Nothing matches “{q}”. {none}
            </p>
          )}
          {items.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => {
                onPick(item);
                setText("");
              }}
            >
              {show(item)}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

const query = (q: string) => ({ status: "active" as const, q, limit: 8 });

export const CustomerPicker = (p: Props<Customer> & { stateNames: Record<string, string> }) => (
  <Picker<Customer>
    {...p}
    kind="customers"
    show={(c) => (
      <>
        <b>{c.name}</b>
        <span className="sub2">
          {c.gstin ? <span className="num">GSTIN {c.gstin}</span> : "No GSTIN (unregistered)"}
          {c.billing?.state_code ? ` · ${p.stateNames[c.billing.state_code] ?? c.billing.state_code}` : ""}
        </span>
      </>
    )}
    fetchItems={(q) => call(() => api.GET("/api/v1/b/{business_id}/customers", { params: { path: { business_id: p.businessId }, query: query(q) } }))}
  />
);

export const ProductPicker = (p: Props<Product> & { exclude?: ReadonlySet<string> }) => (
  <Picker<Product>
    {...p}
    kind="products"
    show={(x) => (
      <>
        <b>{x.name}</b> <span className="sub2 num inline">{x.code}</span>
        <span className="sub2">
          {hsnText(x.hsn)} · {gstText(x)} · {x.uqc} · Rate {/^0*(\.0*)?$/.test(x.sale_rate) ? "—" : formatRupees(x.sale_rate)}
        </span>
      </>
    )}
    fetchItems={(q) => call(() => api.GET("/api/v1/b/{business_id}/products", { params: { path: { business_id: p.businessId }, query: query(q) } }))}
  />
);

type Address = Customer["billing"];
export const addressText = (a: Address | null | undefined, stateNames: Record<string, string>) =>
  a ? [a.line1, a.line2, a.city, a.pin, a.state_code && `${stateNames[a.state_code] ?? ""} (${a.state_code})`.trim()].filter(Boolean).join(", ") : "";

/**
 * The customer on the invoice (#384): name, GSTIN and billing address, with Change to pick another. The details come from the
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
    <section className="ccard" aria-label="Customer">
      <b>{c?.name ?? name}</b>
      <button type="button" className="btn btn-secondary btn-sm" onClick={onChange}>
        Change
      </button>
      {c && (
        <span className="sub2">
          {c.gstin ? <span className="num">GSTIN {c.gstin}</span> : "No GSTIN (unregistered)"}
          {billing && ` · Bill to: ${billing}`}
          {delivery && ` · Ship to: ${delivery}`}
        </span>
      )}
    </section>
  );
}
