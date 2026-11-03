import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { formatDateTimeIst } from "../../format/dates";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { Field } from "../../kit/Field";
import { NotFound } from "../../kit/NotFound";
import { TopBar } from "../../kit/TopBar";

type Grant = components["schemas"]["GrantOut"];
type Grants = components["schemas"]["GrantsOut"];

// The server answers anyone else 404 (support.grant and audit.view, docs/PERMISSIONS.md):
// owners give and end access, admins only see it, billing and CA never reach this screen.
export const SUPPORT_VIEWERS = new Set(["owner", "admin"]);
const REASON_MAX = 500; // GrantIn.reason

const pages = (n: number) => `${n} page${n === 1 ? "" : "s"} viewed`;

/**
 * Settings › Support access (LLD-2 §6.1, §10; mocks v11 M14). The length of a grant is the
 * server's (refdata support.grant_hours), so the button names no hours and the card shows
 * the end time the server sent.
 */
export function SupportPage() {
  const { businessId = "" } = useParams();
  const businesses = useMyBusinesses();
  const business = businesses.data?.find((b) => b.business_id === businessId);
  const canView = Boolean(business && SUPPORT_VIEWERS.has(business.role));
  const isOwner = business?.role === "owner";
  const queryClient = useQueryClient();
  const queryKey = ["b", businessId, "support-grants"];
  const grants = useQuery<Grants, ApiError>({
    queryKey,
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/support-grants", { params: { path: { business_id: businessId } } })),
    enabled: canView,
  });
  const [reason, setReason] = useState("");
  const [said, setSaid] = useState("");
  const refresh = () => queryClient.invalidateQueries({ queryKey });

  const give = useMutation<Grant, ApiError, string>({
    mutationFn: (why) =>
      call(() =>
        api.POST("/api/v1/b/{business_id}/support-grants", {
          params: { path: { business_id: businessId } },
          body: why.trim() ? { reason: why.trim() } : {},
        }),
      ),
    onSuccess: (g) => {
      setReason("");
      setSaid(`Support can view your business until ${formatDateTimeIst(g.expires_at)}. This is in your audit log.`);
      refresh();
    },
  });
  const revoke = useMutation<Grant, ApiError, string>({
    mutationFn: (grantId) =>
      call(() =>
        api.POST("/api/v1/b/{business_id}/support-grants/{grant_id}/revoke", {
          params: { path: { business_id: businessId, grant_id: grantId } },
        }),
      ),
    onSuccess: () => {
      setSaid("Support access ended. It stops on their next request. This is in your audit log.");
      refresh();
    },
    // 409 grant_ended: it ended meanwhile (expired, or another owner ended it); show the list as it is now.
    onError: (e) => {
      if (e.status === 409) refresh();
    },
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
  if (!business || !canView || grants.error?.status === 404) return <NotFound />;

  const list = grants.data?.grants ?? [];
  const active = list.find((g) => g.status === "active");
  const past = list.filter((g) => g.status !== "active");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setSaid("");
    revoke.reset();
    give.mutate(reason);
  };
  const endNow = (grantId: string) => {
    setSaid("");
    give.reset();
    revoke.mutate(grantId);
  };
  const failed = give.error ?? revoke.error;

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page">
        <p className="step">
          <Link to={`/b/${businessId}/home`}>Home</Link>
        </p>
        <h1>Support access</h1>
        <p className="hint">
          Our support team can't see your business unless you let them. Access is read-only, ends on its own, and every page
          they open goes into your audit log.
        </p>
        {!isOwner && <p className="hint">Only an owner can give or end support access.</p>}
        {said && <Banner>{said}</Banner>}
        {failed && <Banner tone="error">{failed.message || errorText(failed)}</Banner>}
        {grants.error && (
          <Banner tone="error">
            {errorText(grants.error)}{" "}
            <Button type="button" variant="link" onClick={() => grants.refetch()}>
              Try again
            </Button>
          </Banner>
        )}
        {grants.isPending && <p aria-busy="true">Loading…</p>}

        {grants.data && active && (
          <section className="card" aria-labelledby="support-on">
            <h2 id="support-on">Support can view your business</h2>
            <p>On until {formatDateTimeIst(active.expires_at)}.</p>
            <p className="hint">
              Given by {active.given_by.name} on {formatDateTimeIst(active.given_at)}
              {active.reason ? ` · “${active.reason}”` : ""} · {pages(active.pages_viewed)} so far
            </p>
            {isOwner && (
              <Button type="button" busy={revoke.isPending} onClick={() => endNow(active.id)}>
                End access now
              </Button>
            )}
          </section>
        )}

        {grants.data && !active && (
          <section className="card" aria-labelledby="support-off">
            <h2 id="support-off">No support access right now</h2>
            {isOwner && (
              <form onSubmit={submit} noValidate>
                <Field
                  label="What it's for (optional)"
                  hint="For example, a ticket number. It goes into your audit log."
                  value={reason}
                  maxLength={REASON_MAX}
                  onChange={(e) => setReason(e.target.value)}
                  error={give.error?.field === "reason" ? give.error.message : undefined}
                />
                <p className="hint">
                  Support can view your products, customers, invoices, uploads and returns. They can't create, change, export,
                  file or invite anything, and they never see your password. Access ends on its own; you can end it sooner.
                </p>
                <Button type="submit" busy={give.isPending}>
                  Give support read-only access
                </Button>
              </form>
            )}
          </section>
        )}

        {grants.data && past.length > 0 && (
          <section aria-labelledby="support-past">
            <h2 id="support-past">Past access</h2>
            <table className="products">
              <thead>
                <tr>
                  <th scope="col">Given</th>
                  <th scope="col">Ended</th>
                  <th scope="col">By</th>
                  <th scope="col">For</th>
                  <th scope="col">Pages viewed</th>
                </tr>
              </thead>
              <tbody>
                {past.map((g) => (
                  <tr key={g.id}>
                    <td data-label="Given">{formatDateTimeIst(g.given_at)}</td>
                    <td data-label="Ended">
                      {g.ended_at ? formatDateTimeIst(g.ended_at) : "—"} · {g.status === "revoked" ? "ended early" : "expired"}
                    </td>
                    <td data-label="By">{g.given_by.name}</td>
                    <td data-label="For">{g.reason ?? "—"}</td>
                    <td data-label="Pages viewed">{g.pages_viewed}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}
      </main>
    </>
  );
}
