import { useInfiniteQuery } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { useStateCodes } from "../../api/useStateCodes";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { NotFound } from "../../kit/NotFound";
import { TopBar } from "../../kit/TopBar";
import { uniqueById, useUrlSearch } from "../../kit/lists";

type Page = components["schemas"]["CustomerPageOut"];
type Status = "active" | "archived" | "all";

export const PAGE_SIZE = 50;
const STATUSES: { value: Status; label: string }[] = [
  { value: "active", label: "Active" },
  { value: "archived", label: "Archived" },
  { value: "all", label: "All" },
];

/**
 * M9 list (LLD-3 §6.2; no M9 artboard yet, so it follows M8). Tab and search live in the URL.
 * GSTINs and warnings are shown as the server sends them: the web applies no GST rule here.
 */
export function CustomersPage() {
  const { businessId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const businesses = useMyBusinesses();
  const business = businesses.data?.find((b) => b.business_id === businessId);
  const states = useStateCodes();
  const status = (STATUSES.find((s) => s.value === params.get("status"))?.value ?? "active") as Status;
  const { search, setSearch, q } = useUrlSearch(params, setParams);

  const setStatus = (value: Status) =>
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      if (value === "active") next.delete("status");
      else next.set("status", value);
      return next;
    });

  const list = useInfiniteQuery<Page, ApiError>({
    queryKey: ["b", businessId, "customers", { status, q }],
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      call(() =>
        api.GET("/api/v1/b/{business_id}/customers", {
          params: {
            path: { business_id: businessId },
            query: { status, q: q || undefined, limit: PAGE_SIZE, offset: pageParam as number },
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
  const stateName = (code: string | null) => (code ? states.data?.find((s) => s.code === code)?.name ?? code : "—");

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page page-wide">
        <div className="actions">
          <h1>Customers</h1>
          <Link className="btn btn-primary" to={`/b/${businessId}/customers/new`}>
            New customer
          </Link>
        </div>
        <div className="field">
          <label htmlFor="customer-search">Search by name or GSTIN</label>
          <input
            id="customer-search"
            type="search"
            aria-describedby="customer-search-hint"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <p id="customer-search-hint" className="hint">
            A GSTIN matches from its first characters.
          </p>
        </div>
        <div className="tabs" role="group" aria-label="Show">
          {STATUSES.map((s) => (
            <button key={s.value} type="button" className="tab" aria-pressed={status === s.value} onClick={() => setStatus(s.value)}>
              {s.label}
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
        {list.isSuccess && items.length === 0 && <p>{q || status !== "active" ? "No customers match." : "No customers yet. Add your first with New customer."}</p>}

        {items.length > 0 && (
          <table className="products">
            <thead>
              <tr>
                <th scope="col">Customer</th>
                <th scope="col">GSTIN</th>
                <th scope="col">Billing state</th>
                <th scope="col">Credit days</th>
              </tr>
            </thead>
            <tbody>
              {items.map((c) => (
                <tr key={c.id}>
                  <td data-label="Customer">
                    <Link to={`/b/${businessId}/customers/${c.id}`}>
                      <strong>{c.name}</strong>
                    </Link>{" "}
                    {(c.warnings.length > 0 || c.status === "archived") && (
                      <span className="chips">
                        {c.warnings.map((w) => (
                          <span key={w.code} className="chip chip-warn">
                            {w.message}
                          </span>
                        ))}
                        {c.status === "archived" && <span className="chip">Archived</span>}
                      </span>
                    )}
                  </td>
                  <td data-label="GSTIN">{c.gstin ?? "Unregistered"}</td>
                  <td data-label="Billing state">{stateName(c.billing.state_code)}</td>
                  <td data-label="Credit days">{c.credit_days}</td>
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
