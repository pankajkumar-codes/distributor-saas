import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { errorText } from "../../api/errors";
import { canEditCatalog } from "../../auth/roles";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { formatRupees } from "../../format/money";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { ErrorDetail } from "../../kit/ErrorDetail";
import { uniqueById, useUrlSearch } from "../../kit/lists";
import { NotFound } from "../../kit/NotFound";
import { TopBar } from "../../kit/TopBar";
import { saleRateProblem } from "../products/saleRate";
import { useSetPrice, useStockList, type Only, type StockItem } from "./useStock";

const FILTERS: { value: Only; label: string }[] = [
  { value: "no_stock", label: "No stock" },
  { value: "price_needed", label: "Price needed" },
];

/** The price box for one row: the selling price per 1 qty, excluding GST, sent to the server as typed. */
function PriceEntry({ businessId, item }: { businessId: string; item: StockItem }) {
  const [text, setText] = useState("");
  const [tried, setTried] = useState(false);
  const problem = saleRateProblem(text, tried);
  const save = useSetPrice(businessId);
  const id = `price-${item.product_id}`;
  return (
    <form
      className="inline-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (!text) return;
        if (saleRateProblem(text, true)) {
          setTried(true);
          return;
        }
        save.mutate({ productId: item.product_id, rate: text.trim() });
      }}
    >
      <input id={id} aria-label={`Price per 1 ${item.uqc} (excl. GST) for ${item.name}`} placeholder={`per 1 ${item.uqc}`} inputMode="decimal" value={text} onChange={(e) => setText(e.target.value)} aria-invalid={problem || save.error ? true : undefined} />
      <Button type="submit" busy={save.isPending} disabled={!text}>
        Save price
      </Button>
      {problem && <p className="error" role="alert">{problem}</p>}
      {!problem && save.error && <p className="error">{save.error.fix ?? (save.error.message || errorText(save.error))}</p>}
    </form>
  );
}

/**
 * Stock (R2-M3): what is on hand for each product, with the "No stock" and "Price needed" views. Stock never
 * blocks a sale: "No stock" is a note, not a stop. The numbers and prices are the server's strings.
 */
export function StockPage() {
  const { businessId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const businesses = useMyBusinesses();
  const business = businesses.data?.find((b) => b.business_id === businessId);
  const only = FILTERS.find((f) => f.value === params.get("only"))?.value ?? null;
  const { search, setSearch, q } = useUrlSearch(params, setParams);
  const list = useStockList(businessId, { q, only, enabled: Boolean(business) });

  if (businesses.isPending) {
    return (
      <main className="page" aria-busy="true">
        <p>Loading…</p>
      </main>
    );
  }
  if (!business) return <NotFound />;
  const mayEdit = canEditCatalog(business.role);
  const items = uniqueById(list.data?.pages.flatMap((p) => p.items.map((i) => ({ ...i, id: i.product_id }))) ?? []);

  const setOnly = (value: Only | null) =>
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      if (value) next.set("only", value);
      else next.delete("only");
      return next;
    });

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page page-wide">
        <p className="step">
          <Link to={`/b/${businessId}/home`}>Home</Link>
        </p>
        <h1>Stock</h1>
        <>
          <p className="hint">Stock comes from the purchase invoices you confirm and drops when you sell. A sale is never blocked when stock is low.</p>
          <div className="field">
            <label htmlFor="stock-search">Search by name or code</label>
            <input id="stock-search" type="search" value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
          <div className="tabs" role="group" aria-label="Filter">
            {FILTERS.map((f) => (
              <button key={f.value} type="button" className="tab" aria-pressed={only === f.value} onClick={() => setOnly(only === f.value ? null : f.value)}>
                {f.label}
              </button>
            ))}
          </div>
          {list.error && (
            <Banner tone="error">
              {errorText(list.error)}
              <ErrorDetail error={list.error} />{" "}
              <Button type="button" variant="link" onClick={() => list.refetch()}>
                Try again
              </Button>
            </Banner>
          )}
          {list.isPending && <p aria-busy="true">Loading…</p>}
          {list.isSuccess && items.length === 0 && <p>{q || only ? "No products match." : "No products yet. Confirm a purchase invoice or add a product to see stock here."}</p>}
          {items.length > 0 && (
            <table className="products">
              <thead>
                <tr>
                  <th scope="col">Product</th>
                  <th scope="col">On hand</th>
                  <th scope="col">Price per 1 qty (excl. GST)</th>
                </tr>
              </thead>
              <tbody>
                {items.map((i) => (
                  <tr key={i.product_id}>
                    <td data-label="Product">
                      <Link to={`/b/${businessId}/products/${i.product_id}`}>
                        <strong>{i.name}</strong>
                      </Link>{" "}
                      <span className="hint">{i.code}</span>
                    </td>
                    <td data-label="On hand">
                      {i.on_hand} {i.uqc}
                      {i.no_stock && <span className="chip chip-warn"> No stock</span>}
                    </td>
                    <td data-label="Price per 1 qty (excl. GST)">
                      {i.price_needed ? (
                        <>
                          <span className="chip chip-warn">Price needed</span>
                          {mayEdit && <PriceEntry businessId={businessId} item={i} />}
                        </>
                      ) : (
                        formatRupees(i.sale_rate)
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {list.hasNextPage && (
            <Button type="button" busy={list.isFetchingNextPage} onClick={() => list.fetchNextPage()}>
              Load more
            </Button>
          )}
        </>
      </main>
    </>
  );
}
