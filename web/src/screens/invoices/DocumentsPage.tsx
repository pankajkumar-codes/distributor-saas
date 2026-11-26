import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { canCreateDocuments } from "../../auth/roles";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { formatDate } from "../../format/dates";
import { formatRupees } from "../../format/money";
import { Banner } from "../../kit/Banner";
import { Loading } from "../../kit/Loading";
import { NotFound } from "../../kit/NotFound";
import { Pager } from "../../kit/Pager";
import { TopBar } from "../../kit/TopBar";

type Page = components["schemas"]["DocumentsOut"];
export const DOCUMENTS_PER_PAGE = 8; // mocks v16: a list fits one laptop screen and pages instead of scrolling

/** The invoices issued so far, newest first, a page at a time. Practice ones say so. */
export function DocumentsPage() {
  const { businessId = "" } = useParams();
  const businesses = useMyBusinesses();
  const business = businesses.data?.find((b) => b.business_id === businessId);
  const allowed = Boolean(business && canCreateDocuments(business.role));
  const [page, setPage] = useState(0);
  const list = useQuery<Page, ApiError>({
    queryKey: ["b", businessId, "drafts", "documents", "page", page],
    enabled: allowed,
    placeholderData: keepPreviousData,
    queryFn: () =>
      call(() =>
        api.GET("/api/v1/b/{business_id}/documents", { params: { path: { business_id: businessId }, query: { limit: DOCUMENTS_PER_PAGE, offset: page * DOCUMENTS_PER_PAGE } } }),
      ),
  });
  if (businesses.isPending) return <main className="page" aria-busy="true"><p>Loading…</p></main>;
  if (!allowed) return <NotFound />;
  const docs = list.data?.documents ?? [];
  return (
    <>
      <TopBar title={business!.display_name} gstin={business!.gstin} />
      <main className="page page-wide">
        <p className="eyebrow">Sell / Issued invoices</p>
        <div className="between">
          <h1>Issued invoices</h1>
          <Link className="btn btn-primary" to={`/b/${businessId}/invoices/new`}>
            New invoice
          </Link>
        </div>
        <p className="hint">Issued invoices are locked. To lower what a buyer owes, open the invoice and choose Adjust invoice.</p>
        {list.error && <Banner tone="error">{errorText(list.error)}</Banner>}
        {list.isPending && <Loading query={list} />}
        {list.isSuccess && (
          <section className="panel" aria-label="Invoices">
            {docs.length === 0 && page === 0 ? (
              <p className="pad">No invoices issued yet. Create a draft to see it here.</p>
            ) : (
              <table className="products">
                <thead>
                  <tr>
                    <th scope="col">Number</th>
                    <th scope="col">Date</th>
                    <th scope="col">Buyer</th>
                    <th scope="col" className="r">
                      Total
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {docs.map((d) => (
                    <tr key={d.id}>
                      <td data-label="Number" className="num">
                        <Link to={`/b/${businessId}/documents/${d.id}`}>
                          <strong>{d.doc_number}</strong>
                        </Link>
                        {d.kind === "credit_note" && <span className="chip"> Credit note</span>}
                        {d.is_practice && <span className="chip chip-warn"> Practice</span>}
                      </td>
                      <td data-label="Date" className="num">
                        {formatDate(d.doc_date)}
                      </td>
                      <td data-label="Buyer">{d.counterparty_name ?? "—"}</td>
                      <td data-label="Total" className="r num">
                        {d.kind === "credit_note" ? `−${formatRupees(d.doc_total)}` : formatRupees(d.doc_total)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {!(docs.length === 0 && page === 0) && <Pager page={page} size={DOCUMENTS_PER_PAGE} shown={docs.length} hasMore={list.data.has_more} noun="invoices" onPage={setPage} />}
          </section>
        )}
      </main>
    </>
  );
}
