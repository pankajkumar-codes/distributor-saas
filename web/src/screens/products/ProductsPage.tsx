import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link, useLocation, useParams, useSearchParams } from "react-router-dom";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { canEditCatalog } from "../../auth/roles";
import { formatRate, formatRupees } from "../../format/money";
import { Banner } from "../../kit/Banner";
import { ErrorDetail } from "../../kit/ErrorDetail";
import { Button } from "../../kit/Button";
import { NotFound } from "../../kit/NotFound";
import { PageHead, SearchBox } from "../../kit/PageHead";
import { Pager } from "../../kit/Pager";
import { TopBar } from "../../kit/TopBar";
import { ROWS_PER_PAGE, useUrlPage, useUrlSearch } from "../../kit/lists";
import { Loading } from "../../kit/Loading";

type Page = components["schemas"]["ProductPageOut"];
type Status = "active" | "archived";
type Filter = "no_hsn" | "rate_unconfirmed";

/** The view chips (mocks v16): All active products, the two to-fix filters, and the archived ones. */
const VIEWS: { key: string; label: string; status: Status; filter: Filter | null }[] = [
  { key: "all", label: "All", status: "active", filter: null },
  { key: "no_hsn", label: "HSN missing", status: "active", filter: "no_hsn" },
  { key: "rate_unconfirmed", label: "Rate not confirmed", status: "active", filter: "rate_unconfirmed" },
  { key: "archived", label: "Archived", status: "archived", filter: null },
];

/**
 * M8 list (LLD-3 §10) in the v16 Ledger look: search, view chips and pages of five, so the
 * screen never scrolls. View, search and page live in the URL, so a Home link or a reload
 * lands on the same rows. Rates and money are shown from the server's strings.
 */
export function ProductsPage() {
  const { businessId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const added = (useLocation().state as { added?: string } | null)?.added;
  const businesses = useMyBusinesses();
  const business = businesses.data?.find((b) => b.business_id === businessId);
  // Old links still work: ?filter=no_hsn and ?status=archived pick the matching chip.
  const view =
    VIEWS.find((v) => v.key === params.get("view")) ??
    VIEWS.find((v) => v.filter && v.filter === params.get("filter")) ??
    (params.get("status") === "archived" ? VIEWS[3] : VIEWS[0]);
  const { search, setSearch, q } = useUrlSearch(params, setParams);
  const { page, setPage } = useUrlPage(params, setParams);

  const pick = (key: string) =>
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      for (const k of ["view", "filter", "status", "page"]) next.delete(k);
      if (key !== "all") next.set("view", key);
      return next;
    });

  const list = useQuery<Page, ApiError>({
    queryKey: ["b", businessId, "products", { status: view.status, filter: view.filter, q, page }],
    queryFn: () =>
      call(() =>
        api.GET("/api/v1/b/{business_id}/products", {
          params: {
            path: { business_id: businessId },
            query: { status: view.status, filter: view.filter, q: q || undefined, limit: ROWS_PER_PAGE, offset: page * ROWS_PER_PAGE },
          },
        }),
      ),
    placeholderData: keepPreviousData,
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
        <Banner tone="error">{errorText(businesses.error)}<ErrorDetail error={businesses.error} /></Banner>
      </main>
    );
  }
  if (!business) return <NotFound />;

  const items = list.data?.items ?? [];
  const narrowed = Boolean(q || view.key !== "all");
  const canEdit = canEditCatalog(business.role);

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page page-wide">
        <PageHead crumbs={[{ label: "Sell" }, { label: "Products" }]} title="Products">
          {canEdit && (
            <>
              <Link className="btn btn-secondary" to={`/b/${businessId}/products/import`}>
                Import from a file
              </Link>
              <Link className="btn btn-primary" to={`/b/${businessId}/products/new`}>
                New product
              </Link>
            </>
          )}
        </PageHead>
        <div className="toolbar">
          <SearchBox id="product-search" label="Search by name, code or barcode" value={search} onChange={setSearch} />
          <div className="row" role="group" aria-label="Show">
            {VIEWS.map((v) => (
              <button key={v.key} type="button" className="fchip" aria-pressed={view.key === v.key} onClick={() => pick(v.key)}>
                {v.label}
              </button>
            ))}
          </div>
        </div>

        {added && <Banner>Added {added}.</Banner>}
        {list.error && (
          <Banner tone="error">
            {errorText(list.error)}<ErrorDetail error={list.error} />{" "}
            <Button type="button" variant="link" onClick={() => list.refetch()}>
              Try again
            </Button>
          </Banner>
        )}
        {list.isPending && <Loading query={list} />}

        {list.isSuccess && (
          <section className="panel" aria-labelledby="products-h">
            <div className="panel-h">
              <h2 id="products-h">{view.key === "all" ? "All products" : view.label}</h2>
            </div>
            {items.length === 0 ? (
              <p className="empty">
                {page > 0 ? "No more products." : narrowed ? "No products match." : canEdit ? "No products yet. Add your first with New product." : "No products yet."}
              </p>
            ) : (
              <div className="tablewrap">
                <table className="ltable">
                  <thead>
                    <tr>
                      <th scope="col">Product</th>
                      <th scope="col">HSN</th>
                      <th scope="col">Unit</th>
                      <th scope="col" className="r">
                        Sale rate (excl. GST)
                      </th>
                      <th scope="col" className="r">
                        MRP
                      </th>
                      <th scope="col" className="r">
                        GST rate
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((p) => (
                      <tr key={p.id}>
                        <td>
                          <Link className="pname" to={`/b/${businessId}/products/${p.id}`}>
                            {p.name}
                          </Link>{" "}
                          {p.status === "archived" && <span className="chip">Archived</span>}
                          <span className="sub2 num">{p.code}</span>
                        </td>
                        <td className="num">{p.hsn ?? <span className="chip chip-warn">HSN missing</span>}</td>
                        <td className="num">{p.uqc}</td>
                        <td className="r num">{formatRupees(p.sale_rate)}</td>
                        <td className="r num">{p.mrp ? formatRupees(p.mrp) : "—"}</td>
                        <td className="r num">
                          {p.rate_on ? formatRate(p.rate_on.rate) : p.tax_category === "taxable" ? "—" : CATEGORY[p.tax_category] ?? "—"}
                          {p.rate_on && !p.rate_on.confirmed && (
                            <>
                              {" "}
                              <span className="chip chip-warn">Not confirmed</span>
                            </>
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

const CATEGORY: Record<string, string> = { exempt: "Exempt", nil_rated: "Nil rated", non_gst: "Non-GST" };
