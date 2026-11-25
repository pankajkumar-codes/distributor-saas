import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { errorText } from "../../api/errors";
import { canEditCatalog } from "../../auth/roles";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { formatRupees } from "../../format/money";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { ErrorDetail } from "../../kit/ErrorDetail";
import { ROWS_PER_PAGE, useUrlPage, useUrlSearch } from "../../kit/lists";
import { PageHead, SearchBox } from "../../kit/PageHead";
import { Pager } from "../../kit/Pager";
import { NotFound } from "../../kit/NotFound";
import { TopBar } from "../../kit/TopBar";
import { saleRateProblem } from "../products/saleRate";
import { useSetPrice, useStockList, type Only, type StockItem } from "./useStock";
import { Loading } from "../../kit/Loading";

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
  const { page, setPage } = useUrlPage(params, setParams);
  const list = useStockList(businessId, { q, only, page, size: ROWS_PER_PAGE, enabled: Boolean(business) });

  if (businesses.isPending) {
    return (
      <main className="page" aria-busy="true">
        <p>Loading…</p>
      </main>
    );
  }
  if (!business) return <NotFound />;
  const mayEdit = canEditCatalog(business.role);
  const items = list.data?.items ?? [];

  const setOnly = (value: Only | null) =>
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete("page");
      if (value) next.set("only", value);
      else next.delete("only");
      return next;
    });

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page page-wide">
        <PageHead
          crumbs={[{ label: "Sell" }, { label: "Stock" }]}
          title="Stock"
          sub="Stock comes from the purchase invoices you confirm and drops when you sell. A sale is never blocked when stock is low."
        />
        <div className="toolbar">
          <SearchBox id="stock-search" label="Search by name or code" value={search} onChange={setSearch} />
          <div className="row" role="group" aria-label="Filter">
            {FILTERS.map((f) => (
              <button key={f.value} type="button" className="fchip" aria-pressed={only === f.value} onClick={() => setOnly(only === f.value ? null : f.value)}>
                {f.label}
              </button>
            ))}
          </div>
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
        {list.isPending && <Loading query={list} />}
        {list.isSuccess && (
          <section className="panel" aria-labelledby="stock-h">
            <div className="panel-h">
              <h2 id="stock-h">{only ? FILTERS.find((f) => f.value === only)!.label : "On hand today"}</h2>
            </div>
            {items.length === 0 ? (
              <p className="empty">{page > 0 ? "No more products." : q || only ? "No products match." : "No products yet. Confirm a purchase invoice or add a product to see stock here."}</p>
            ) : (
              <div className="tablewrap">
                <table className="ltable">
                  <thead>
                    <tr>
                      <th scope="col">Product</th>
                      <th scope="col" className="r">
                        On hand
                      </th>
                      <th scope="col" className="r">
                        Price per 1 qty (excl. GST)
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((i) => (
                      <tr key={i.product_id}>
                        <td>
                          <Link className="pname" to={`/b/${businessId}/products/${i.product_id}`}>
                            {i.name}
                          </Link>
                          <span className="sub2 num">{i.code}</span>
                        </td>
                        <td className="r num">
                          {i.on_hand} {i.uqc}
                          {i.no_stock && (
                            <>
                              {" "}
                              <span className="chip chip-warn">No stock</span>
                            </>
                          )}
                        </td>
                        <td className="r num">
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
              </div>
            )}
            {(page > 0 || list.data.has_more) && (
              <Pager page={page} size={ROWS_PER_PAGE} shown={items.length} hasMore={list.data.has_more} noun="products" onPage={setPage} />
            )}
          </section>
        )}
      </main>
    </>
  );
}
