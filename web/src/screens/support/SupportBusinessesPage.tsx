import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { formatDateTimeIst } from "../../format/dates";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { NotFound } from "../../kit/NotFound";
import { TopBar } from "../../kit/TopBar";
import { msUntilFirst } from "../settings/SupportPage";

type Grants = components["schemas"]["SupportGrants"];

/**
 * Support staff's landing page (LLD-2 §6.2): the businesses whose owner has given support
 * access now, soonest to end first. The list is the whole support team's, by design. Anyone
 * who isn't support with TOTP on gets the server's 404, shown as not found.
 */
export function SupportBusinessesPage() {
  const grants = useQuery<Grants, ApiError>({
    queryKey: ["support", "grants"],
    queryFn: () => call(() => api.GET("/api/v1/support/grants")),
    // Drop a business from the list when its access ends, without a reload.
    refetchInterval: (q) => msUntilFirst(q.state.data?.grants.map((g) => g.expires_at) ?? []),
  });
  if (grants.error?.status === 404) return <NotFound />;
  const list = grants.data?.grants ?? [];

  return (
    <>
      <TopBar />
      <main className="page">
        <h1>Businesses you can view</h1>
        <p className="hint">
          Owners give support read-only access for a limited time. Every page you open goes into that business's audit log.
        </p>
        {grants.isPending && <p aria-busy="true">Loading…</p>}
        {grants.error && (
          <Banner tone="error">
            {errorText(grants.error)}{" "}
            <Button type="button" variant="link" onClick={() => grants.refetch()}>
              Try again
            </Button>
          </Banner>
        )}
        {grants.data && list.length === 0 && <p>No business has given support access right now.</p>}
        {list.length > 0 && (
          <ul className="list">
            {list.map((g) => (
              <li key={g.grant_id}>
                <Link to={`/b/${g.business_id}/home`}>{g.business_name}</Link>
                <span className="hint"> · access ends {formatDateTimeIst(g.expires_at)}</span>
              </li>
            ))}
          </ul>
        )}
      </main>
    </>
  );
}
