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
import { useMe } from "../../auth/useMe";
import { msUntilFirst } from "../settings/SupportPage";

type Grants = components["schemas"]["SupportGrants"];

/**
 * Support staff's landing page (LLD-2 §6.2): the businesses whose owner has given support
 * access now, soonest to end first. The list is the whole support team's, by design. Anyone
 * who isn't support with TOTP on gets the server's 404, shown as not found, except support
 * staff who haven't turned TOTP on yet: they are sent to turn it on (L2-5).
 */
export function SupportBusinessesPage() {
  const grants = useQuery<Grants, ApiError>({
    queryKey: ["support", "grants"],
    queryFn: () => call(() => api.GET("/api/v1/support/grants")),
    // Drop a business from the list when its access ends, without a reload.
    refetchInterval: (q) => msUntilFirst(q.state.data?.grants.map((g) => g.expires_at) ?? []),
  });
  const refused = grants.error?.status === 404;
  const me = useMe({ enabled: refused });
  if (refused && me.data?.user.is_support && !me.data.user.totp_enabled) {
    return (
      <>
        <TopBar />
        <main className="page">
          <h1>Turn on two-step sign-in first</h1>
          <p>Support staff need two-step sign-in on before they can view any business.</p>
          <Link to="/account/security">Turn on two-step sign-in</Link>
        </main>
      </>
    );
  }
  if (refused && (me.data || me.error)) return <NotFound />;
  if (refused) {
    return (
      <main className="page" aria-busy="true">
        <p>Loading…</p>
      </main>
    );
  }
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
        {grants.data && (
          <nav className="card" aria-labelledby="tools">
            <h2 id="tools">Support tools</h2>
            <ul className="list">
              <li>
                <Link to="/support/totp-recovery">Remove someone's two-step sign-in</Link>
              </li>
              <li>
                <Link to="/account/security">Your two-step sign-in</Link>
              </li>
            </ul>
          </nav>
        )}
      </main>
    </>
  );
}
