import { useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";

import { signOut } from "../auth/session";
import type { Membership } from "../auth/landing";
import { SUPPORT_ROLE } from "../auth/useMyBusinesses";
import { formatDateTimeIst } from "../format/dates";
import { Button } from "./Button";

export function TopBar({ title, gstin }: { title?: string; gstin?: string | null }) {
  const navigate = useNavigate();
  const { businessId } = useParams();
  // The page's own business list, read from the cache without subscribing: the page has
  // already loaded it, and TopBar must never fetch it or refetch it on its own.
  const businesses = useQueryClient().getQueryData<Membership[]>(["me", "businesses"]);
  const support = businesses?.find((b) => b.business_id === businessId && b.role === SUPPORT_ROLE);
  return (
    <>
      {support && (
        // LLD-2 §6.2: fixed on every screen of a business opened under a grant.
        <p className="banner banner-info support-view" role="status">
          Support view · read-only
          {support.support_ends_at ? ` · ends ${formatDateTimeIst(support.support_ends_at)}` : ""}
        </p>
      )}
      <header className="topbar">
        <div>
          {title && <strong>{title}</strong>}
          {gstin && <span className="hint"> · GSTIN {gstin}</span>}
        </div>
        <Button
          type="button"
          variant="link"
          onClick={async () => {
            await signOut({ rememberPage: false });
            navigate("/signin", { replace: true });
          }}
        >
          Sign out
        </Button>
      </header>
    </>
  );
}
