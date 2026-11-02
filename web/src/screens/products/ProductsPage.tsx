import { useInfiniteQuery } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { formatRate, formatRupees } from "../../format/money";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { NotFound } from "../../kit/NotFound";
import { TopBar } from "../../kit/TopBar";
import { uniqueById, useUrlSearch } from "../../kit/lists";

type Page = components["schemas"]["ProductPageOut"];
type Product = components["schemas"]["ProductOut"];
type Status = "active" | "archived" | "all";
type Filter = "no_hsn" | "rate_unconfirmed";

export const PAGE_SIZE = 50;
const STATUSES: { value: Status; label: string }[] = [
  { value: "active", label: "Active" },
  { value: "archived", label: "Archived" },
  { value: "all", label: "All" },
];
const FILTERS: { value: Filter; label: string }[] = [
  { value: "no_hsn", label: "No HSN" },
  { value: "rate_unconfirmed", label: "Rate not confirmed" },
];

function Chips({ p }: { p: Product }) {
  const unconfirmed = p.rate_on && !p.rate_on.confirmed;
  if (p.hsn && !unconfirmed && p.status === "active") return null;
  return (
    <span className="chips">
      {!p.hsn && <span className="chip chip-warn">HSN missing</span>}
      {unconfirmed && <span className="chip chip-warn">Not confirmed</span>}
      {p.status === "archived" && <span className="chip">Archived</span>}
    </span>
  );
}

/**
 * M8 list (LLD-3 §10). Tab, filter and search live in the URL, so a Home link or a reload
 * lands on the same view. Rates and money are shown from the server's strings.
 */
export function ProductsPage() {
  const { businessId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const businesses = useMyBusinesses();
  const business = businesses.data?.find((b) => b.business_id === businessId);
  const status = (STATUSES.find((s) => s.value === params.get("status"))?.value ?? "active") as Status;
  const filter = FILTERS.find((f) => f.value === params.get("filter"))?.value ?? null;
  const { search, setSearch, q } = useUrlSearch(params, setParams);

  const set = (key: string, value: string | null) =>
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      if (value) next.set(key, value);
      else next.delete(key);
      return next;
    });

  const list = useInfiniteQuery<Page, ApiError>({
    queryKey: ["b", businessId, "products", { status, filter, q }],
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      call(() =>
        api.GET("/api/v1/b/{business_id}/products", {
          params: {
            path: { business_id: businessId },
            query: { status, filter, q: q || undefined, limit: PAGE_SIZE, offset: pageParam as number },
          },
        }),
      ),
    getNextPageParam: (last, pages) => (last.has_more ? pages.length * PAGE_SIZE : undefined),
    enabled: Boolean(business),
  });

  if (businesses.isPending) {
    return (
      <main className="page" aria-busy="true">
        <p>Loading…</p>
      </main>
    );
  }
  if (businesses.error) {
    return (
      <main className="page">
        <Banner tone="error">{errorText(businesses.error)}</Banner>
      </main>
    );
  }
  if (!business) return <NotFound />;

  const items = uniqueById(list.data?.pages.flatMap((p) => p.items) ?? []);
  const narrowed = Boolean(q || filter || status !== "active");

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page page-wide">
        <div className="actions">
          <h1>Products</h1>
          <Link className="btn btn-primary" to={`/b/${businessId}/products/new`}>
            New product
          </Link>
        </div>
        <div className="field">
          <label htmlFor="product-search">Search by name, code or barcode</label>
          <input id="product-search" type="search" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <div className="tabs" role="group" aria-label="Show">
          {STATUSES.map((s) => (
            <button
              key={s.value}
              type="button"
              className="tab"
              aria-pressed={status === s.value}
              onClick={() => set("status", s.value === "active" ? null : s.value)}
            >
              {s.label}
            </button>
          ))}
        </div>
        <div className="tabs" role="group" aria-label="Filter">
          {FILTERS.map((f) => (
            <button
              key={f.value}
              type="button"
              className="tab"
              aria-pressed={filter === f.value}
              onClick={() => set("filter", filter === f.value ? null : f.value)}
            >
              {f.label}
            </button>
          ))}
        </div>

        {list.error && (
          <Banner tone="error">
            {errorText(list.error)}{" "}
            <Button type="button" variant="link" onClick={() => list.refetch()}>
              Try again
            </Button>
          </Banner>
        )}
        {list.isPending && <p aria-busy="true">Loading…</p>}
        {list.isSuccess && items.length === 0 && (
          <p>{narrowed ? "No products match." : "No products yet. Add your first with New product."}</p>
        )}

        {items.length > 0 && (
          <table className="products">
            <thead>
              <tr>
                <th scope="col">Product</th>
                <th scope="col">HSN</th>
                <th scope="col">Unit</th>
                <th scope="col">Sale rate (excl. GST)</th>
                <th scope="col">GST rate</th>
              </tr>
            </thead>
            <tbody>
              {items.map((p) => (
                <tr key={p.id}>
                  <td data-label="Product">
                    <Link to={`/b/${businessId}/products/${p.id}`}>
                      <strong>{p.name}</strong>
                    </Link>{" "}
                    <span className="hint">{p.code}</span> <Chips p={p} />
                  </td>
                  <td data-label="HSN">{p.hsn ?? "—"}</td>
                  <td data-label="Unit">{p.uqc}</td>
                  <td data-label="Sale rate (excl. GST)">{formatRupees(p.sale_rate)}</td>
                  <td data-label="GST rate">
                    {p.rate_on ? formatRate(p.rate_on.rate) : p.tax_category === "taxable" ? "—" : CATEGORY[p.tax_category] ?? "—"}
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
      </main>
    </>
  );
}

const CATEGORY: Record<string, string> = { exempt: "Exempt", nil_rated: "Nil rated", non_gst: "Non-GST" };
