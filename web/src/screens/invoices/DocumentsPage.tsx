import { useInfiniteQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { canCreateDocuments } from "../../auth/roles";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { formatDate } from "../../format/dates";
import { formatRupees } from "../../format/money";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { NotFound } from "../../kit/NotFound";
import { TopBar } from "../../kit/TopBar";
import { Loading } from "../../kit/Loading";

type Page = components["schemas"]["DocumentsOut"];
const SIZE = 25;

/** The invoices issued so far, newest first. Practice ones say so. */
export function DocumentsPage() {
  const { businessId = "" } = useParams();
  const businesses = useMyBusinesses();
  const business = businesses.data?.find((b) => b.business_id === businessId);
  const allowed = Boolean(business && canCreateDocuments(business.role));
  const list = useInfiniteQuery<Page, ApiError>({
    queryKey: ["b", businessId, "drafts", "documents"],
    initialPageParam: 0,
    enabled: allowed,
    queryFn: ({ pageParam }) => call(() => api.GET("/api/v1/b/{business_id}/documents", { params: { path: { business_id: businessId }, query: { limit: SIZE, offset: pageParam as number } } })),
    getNextPageParam: (last, pages) => (last.has_more ? pages.length * SIZE : undefined),
  });
  if (businesses.isPending) return <main className="page" aria-busy="true"><p>Loading…</p></main>;
  if (!allowed) return <NotFound />;
  const docs = list.data?.pages.flatMap((p) => p.documents) ?? [];
  return (
    <>
      <TopBar title={business!.display_name} gstin={business!.gstin} />
      <main className="page page-wide">
        <p className="step">
          <Link to={`/b/${businessId}/home`}>Home</Link>
        </p>
        <h1>Issued invoices</h1>
        {list.error && <Banner tone="error">{errorText(list.error)}</Banner>}
        {list.isPending && <Loading query={list} />}
        {list.isSuccess && docs.length === 0 && <p>No invoices issued yet. Finalize a draft to see it here.</p>}
        {docs.length > 0 && (
          <table className="products">
            <thead>
              <tr>
                <th scope="col">Number</th>
                <th scope="col">Date</th>
                <th scope="col">Buyer</th>
                <th scope="col">Total</th>
              </tr>
            </thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id}>
                  <td data-label="Number">
                    <Link to={`/b/${businessId}/documents/${d.id}`}>
                      <strong>{d.doc_number}</strong>
                    </Link>
                    {d.is_practice && <span className="chip chip-warn"> Practice</span>}
                  </td>
                  <td data-label="Date">{formatDate(d.doc_date)}</td>
                  <td data-label="Buyer">{d.counterparty_name ?? "—"}</td>
                  <td data-label="Total">{formatRupees(d.doc_total)}</td>
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
