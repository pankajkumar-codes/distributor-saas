import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { canCreateDocuments } from "../../auth/roles";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { formatDate, formatDateTimeIst } from "../../format/dates";
import { formatRupees } from "../../format/money";
import { Banner } from "../../kit/Banner";
import { Loading } from "../../kit/Loading";
import { NotFound } from "../../kit/NotFound";
import { Pager } from "../../kit/Pager";
import { TopBar } from "../../kit/TopBar";
import { useCursorPages } from "../../kit/useCursorPages";
import { buyerOf } from "./buyer";

type Page = components["schemas"]["DraftPageOut"];
export const DRAFTS_PER_PAGE = 8; // mocks v16: a list fits one laptop screen and pages instead of scrolling

/** Invoices saved as drafts and not finalized yet, the most recently saved first, a page at a time. */
export function DraftsPage() {
  const { businessId = "" } = useParams();
  const businesses = useMyBusinesses();
  const business = businesses.data?.find((b) => b.business_id === businessId);
  const allowed = Boolean(business && canCreateDocuments(business.role));
  const pages = useCursorPages();
  const list = useQuery<Page, ApiError>({
    queryKey: ["b", businessId, "drafts", "list", "page", pages.cursor],
    enabled: allowed,
    placeholderData: keepPreviousData,
    queryFn: () =>
      call(() =>
        api.GET("/api/v1/b/{business_id}/drafts", {
          params: { path: { business_id: businessId }, query: { kind: "invoice", limit: DRAFTS_PER_PAGE, ...(pages.cursor ? { cursor: pages.cursor } : {}) } },
        }),
      ),
  });
  if (businesses.isPending) return <main className="page" aria-busy="true"><p>Loading…</p></main>;
  if (!allowed) return <NotFound />;
  const drafts = list.data?.items ?? [];
  return (
    <>
      <TopBar title={business!.display_name} gstin={business!.gstin} />
      <main className="page page-wide">
        <p className="eyebrow">Sell / Draft invoices</p>
        <div className="between">
          <h1>Draft invoices</h1>
          <Link className="btn btn-primary" to={`/b/${businessId}/invoices/new`}>
            Start a new invoice
          </Link>
        </div>
        <p className="hint">Drafts are not GST records. Open one to finish and create it.</p>
        {list.error && <Banner tone="error">{errorText(list.error)}</Banner>}
        {list.isPending && <Loading query={list} />}
        {list.isSuccess && (
          <section className="panel" aria-label="Drafts">
            {drafts.length === 0 && pages.page === 0 ? (
              <p className="pad">
                No drafts. <Link to={`/b/${businessId}/invoices/new`}>Start a new invoice</Link>
              </p>
            ) : (
              <table className="products">
                <thead>
                  <tr>
                    <th scope="col">Buyer</th>
                    <th scope="col">Invoice date</th>
                    <th scope="col">Status</th>
                    <th scope="col">Last saved</th>
                    <th scope="col" className="r">
                      Total
                    </th>
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
                      <td data-label="Invoice date" className="num">
                        {d.doc_date ? formatDate(d.doc_date) : <span className="hint">Day you create it</span>}
                      </td>
                      <td data-label="Status">
                        {d.ready === null ? <span className="chip">Not checked yet</span> : d.ready ? <span className="chip chip-ok">Ready to create</span> : <span className="chip chip-warn">Needs fixes</span>}
                      </td>
                      <td data-label="Last saved" className="num">
                        {formatDateTimeIst(d.updated_at)}
                      </td>
                      <td data-label="Total" className="r num">
                        {d.total ? formatRupees(d.total) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {!(drafts.length === 0 && pages.page === 0) && <Pager page={pages.page} size={DRAFTS_PER_PAGE} shown={drafts.length} hasMore={list.data.has_more} noun="drafts" onPage={(to) => pages.go(to, list.data?.next_cursor)} />}
          </section>
        )}
      </main>
    </>
  );
}
