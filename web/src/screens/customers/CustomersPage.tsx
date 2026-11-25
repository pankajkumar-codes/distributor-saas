import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link, useLocation, useParams, useSearchParams } from "react-router-dom";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { useStateCodes } from "../../api/useStateCodes";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { canEditCatalog } from "../../auth/roles";
import { Banner } from "../../kit/Banner";
import { ErrorDetail } from "../../kit/ErrorDetail";
import { Button } from "../../kit/Button";
import { NotFound } from "../../kit/NotFound";
import { PageHead, SearchBox } from "../../kit/PageHead";
import { Pager } from "../../kit/Pager";
import { TopBar } from "../../kit/TopBar";
import { ROWS_PER_PAGE, useUrlPage, useUrlSearch } from "../../kit/lists";
import { Loading } from "../../kit/Loading";

type Page = components["schemas"]["CustomerPageOut"];
type Status = "active" | "archived" | "all";

const STATUSES: { value: Status; label: string }[] = [
  { value: "active", label: "Active" },
  { value: "archived", label: "Archived" },
  { value: "all", label: "All" },
];

/**
 * M9 list (LLD-3 §6.2) in the v16 Ledger look: search, status chips and pages of five, so the
 * screen never scrolls. Status, search and page live in the URL. GSTINs and warnings are shown
 * as the server sends them: the web applies no GST rule here.
 */
export function CustomersPage() {
  const { businessId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const businesses = useMyBusinesses();
  const business = businesses.data?.find((b) => b.business_id === businessId);
  const states = useStateCodes();
  const added = (useLocation().state as { added?: string } | null)?.added;
  const status = (STATUSES.find((s) => s.value === params.get("status"))?.value ?? "active") as Status;
  const { search, setSearch, q } = useUrlSearch(params, setParams);
  const { page, setPage } = useUrlPage(params, setParams);

  const setStatus = (value: Status) =>
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete("page");
      if (value === "active") next.delete("status");
      else next.set("status", value);
      return next;
    });

  const list = useQuery<Page, ApiError>({
    queryKey: ["b", businessId, "customers", { status, q, page }],
    queryFn: () =>
      call(() =>
        api.GET("/api/v1/b/{business_id}/customers", {
          params: {
            path: { business_id: businessId },
            query: { status, q: q || undefined, limit: ROWS_PER_PAGE, offset: page * ROWS_PER_PAGE },
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
  const stateName = (code: string | null) => (code ? states.data?.find((s) => s.code === code)?.name ?? code : "—");
  const canEdit = canEditCatalog(business.role);

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page page-wide">
        <PageHead crumbs={[{ label: "Sell" }, { label: "Customers" }]} title="Customers">
          {canEdit && (
            <Link className="btn btn-primary" to={`/b/${businessId}/customers/new`}>
              New customer
            </Link>
          )}
        </PageHead>
        <div className="toolbar">
          <SearchBox id="customer-search" label="Search by name or GSTIN" value={search} onChange={setSearch} />
          <div className="row" role="group" aria-label="Show">
            {STATUSES.map((s) => (
              <button key={s.value} type="button" className="fchip" aria-pressed={status === s.value} onClick={() => setStatus(s.value)}>
                {s.label}
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
          <section className="panel" aria-labelledby="customers-h">
            <div className="panel-h">
              <h2 id="customers-h">{status === "active" ? "All customers" : status === "archived" ? "Archived customers" : "Active and archived"}</h2>
            </div>
            {items.length === 0 ? (
              <p className="empty">
                {page > 0 ? "No more customers." : q || status !== "active" ? "No customers match." : canEdit ? "No customers yet. Add your first with New customer." : "No customers yet."}
              </p>
            ) : (
              <div className="tablewrap">
                <table className="ltable">
                  <thead>
                    <tr>
                      <th scope="col">Customer</th>
                      <th scope="col">GSTIN</th>
                      <th scope="col">Billing state</th>
                      <th scope="col" className="r">
                        Credit days
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((c) => (
                      <tr key={c.id}>
                        <td>
                          <Link className="pname" to={`/b/${businessId}/customers/${c.id}`}>
                            {c.name}
                          </Link>{" "}
                          {c.status === "archived" && <span className="chip">Archived</span>}
                          {c.warnings.map((w) => (
                            <span key={w.code} className="sub2">
                              {w.message}
                            </span>
                          ))}
                        </td>
                        <td className={c.gstin ? "num" : "sub2"}>{c.gstin ?? "None"}</td>
                        <td>
                          {stateName(c.billing.state_code)} {c.billing.state_code && <span className="faint">({c.billing.state_code})</span>}
                        </td>
                        <td className="r num">{c.credit_days}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {(page > 0 || list.data.has_more) && (
              <Pager page={page} size={ROWS_PER_PAGE} shown={items.length} hasMore={list.data.has_more} noun="customers" onPage={setPage} />
            )}
          </section>
        )}
      </main>
    </>
  );
}
