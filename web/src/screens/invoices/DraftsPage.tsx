import { useInfiniteQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { canCreateDocuments } from "../../auth/roles";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { formatDate, formatDateTimeIst } from "../../format/dates";
import { formatRupees } from "../../format/money";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { Loading } from "../../kit/Loading";
import { NotFound } from "../../kit/NotFound";
import { TopBar } from "../../kit/TopBar";

type Page = components["schemas"]["DraftPageOut"];
type Draft = Page["items"][number];

/** Who the draft is for: the customer's name as saved on it, the cash buyer's, or nothing yet. */
function buyerOf(d: Draft): string {
  const name = (v: unknown) => (typeof v === "string" && v.trim() ? v : null);
  if (d.cash_buyer) return name((d.cash_buyer as Record<string, unknown>).name) ?? "Cash sale";
  return name((d.bill_to as Record<string, unknown> | null)?.name) ?? "No buyer yet";
}

/** Invoices saved as drafts and not finalized yet, the most recently saved first. */
export function DraftsPage() {
  const { businessId = "" } = useParams();
  const businesses = useMyBusinesses();
  const business = businesses.data?.find((b) => b.business_id === businessId);
  const allowed = Boolean(business && canCreateDocuments(business.role));
  const list = useInfiniteQuery<Page, ApiError>({
    queryKey: ["b", businessId, "drafts", "list"],
    initialPageParam: null,
    enabled: allowed,
    queryFn: ({ pageParam }) =>
      call(() =>
        api.GET("/api/v1/b/{business_id}/drafts", {
          params: { path: { business_id: businessId }, query: { kind: "invoice", ...(pageParam ? { cursor: pageParam as string } : {}) } },
        }),
      ),
    getNextPageParam: (last) => (last.has_more ? last.next_cursor : undefined),
  });
  if (businesses.isPending) return <main className="page" aria-busy="true"><p>Loading…</p></main>;
  if (!allowed) return <NotFound />;
  const drafts = list.data?.pages.flatMap((p) => p.items) ?? [];
  return (
    <>
      <TopBar title={business!.display_name} gstin={business!.gstin} />
      <main className="page page-wide">
        <p className="step">
          <Link to={`/b/${businessId}/home`}>Home</Link>
        </p>
        <h1>Draft invoices</h1>
        <p className="hint">Drafts are not GST records. Open one to finish and finalize it.</p>
        {list.error && <Banner tone="error">{errorText(list.error)}</Banner>}
        {list.isPending && <Loading query={list} />}
        {list.isSuccess && drafts.length === 0 && (
          <p>
            No drafts. <Link to={`/b/${businessId}/invoices/new`}>Start a new invoice</Link>
          </p>
        )}
        {drafts.length > 0 && (
          <table className="products">
            <thead>
              <tr>
                <th scope="col">Buyer</th>
                <th scope="col">Invoice date</th>
                <th scope="col">Total</th>
                <th scope="col">Status</th>
                <th scope="col">Last saved</th>
              </tr>
            </thead>
            <tbody>
              {drafts.map((d) => (
                <tr key={d.id}>
                  <td data-label="Buyer">
                    <Link to={`/b/${businessId}/invoices/${d.id}`}>
                      <strong>{buyerOf(d)}</strong>
                    </Link>
                  </td>
                  <td data-label="Invoice date">{d.doc_date ? formatDate(d.doc_date) : "—"}</td>
                  <td data-label="Total">{d.total ? formatRupees(d.total) : "—"}</td>
                  <td data-label="Status">
                    {d.ready === null ? <span className="chip">Not checked yet</span> : d.ready ? <span className="chip chip-ok">Ready to finalize</span> : <span className="chip chip-warn">Needs fixes</span>}
                  </td>
                  <td data-label="Last saved">{formatDateTimeIst(d.updated_at)}</td>
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
