import { useQueryClient } from "@tanstack/react-query";
import { NavLink, useNavigate, useParams } from "react-router-dom";

import { signOut } from "../auth/session";
import type { Membership } from "../auth/landing";
import { canViewUploads } from "../auth/roles";
import { SUPPORT_ROLE } from "../auth/useMyBusinesses";
import { formatDateTimeIst } from "../format/dates";
import { Button } from "./Button";

/** Two letters for the brand tile, from the business name ("Vaashi Essentials" gives "VE"). */
function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  const letters = words.length > 1 ? words[0][0] + words[1][0] : (words[0] ?? "").slice(0, 2);
  return letters.toUpperCase();
}

export function TopBar({ title, gstin }: { title?: string; gstin?: string | null }) {
  const navigate = useNavigate();
  const { businessId } = useParams();
  // The page's own business list, read from the cache without subscribing: the page has
  // already loaded it, and TopBar must never fetch it or refetch it on its own.
  const businesses = useQueryClient().getQueryData<Membership[]>(["me", "businesses"]);
  const mine = businesses?.find((b) => b.business_id === businessId);
  const support = mine?.role === SUPPORT_ROLE ? mine : undefined;
  const base = businessId && mine ? `/b/${businessId}` : null;
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
        <div className="topbar-in">
          <div className="brand">
            {title && (
              <div className="mark" aria-hidden="true">
                {initials(title)}
              </div>
            )}
            <div>
              {title && <strong>{title}</strong>}
              {gstin && <div className="hint num">GSTIN {gstin}</div>}
            </div>
          </div>
          {base && mine && (
            <nav className="nav" aria-label="Main">
              <NavLink to={`${base}/home`}>Dashboard</NavLink>
              <NavLink to={`${base}/filing`}>Filing home</NavLink>
              {canViewUploads(mine.role) && <NavLink to={`${base}/uploads`}>Uploads</NavLink>}
              <NavLink to={`${base}/settings`}>Business setup</NavLink>
            </nav>
          )}
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
        </div>
      </header>
    </>
  );
}
