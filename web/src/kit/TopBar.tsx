import { useQueryClient } from "@tanstack/react-query";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";

import { signOut } from "../auth/session";
import type { Membership } from "../auth/landing";
import { canCreateDocuments, canViewUploads } from "../auth/roles";
import { SUPPORT_ROLE } from "../auth/useMyBusinesses";
import { FEATURES } from "../features";
import { formatDateTimeIst } from "../format/dates";
import { Button } from "./Button";
import { GlobalSearch } from "./GlobalSearch";
import { NAV_GROUPS, PHONE_TABS, currentNav, type NavItem } from "./nav";
import { useReturnLinks } from "./useReturnLinks";

/** Two letters for the brand tile, from the business name ("Vaashi Essentials" gives "VE"). */
function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  const letters = words.length > 1 ? words[0][0] + words[1][0] : (words[0] ?? "").slice(0, 2);
  return letters.toUpperCase();
}

function Icon({ d }: { d: string }) {
  // Paths are fixed strings from nav.ts (mocks v16), never user data.
  return <svg viewBox="0 0 24 24" aria-hidden="true" dangerouslySetInnerHTML={{ __html: d }} />;
}

/**
 * The app shell from mocks v16 (Ledger): a left sidebar with the business and every screen,
 * grouped Home / Sell / GST filing / Settings, and a top bar with search and Sign out.
 * On a phone the sidebar gives way to a bottom tab bar. A page renders <TopBar/> first and
 * its <main className="page"> next to it; CSS places the main beside the sidebar.
 */
export function TopBar({ title, gstin }: { title?: string; gstin?: string | null }) {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const { businessId } = useParams();
  // The page's own business list, read from the cache without subscribing: the page has
  // already loaded it, and TopBar must never fetch it or refetch it on its own.
  const businesses = useQueryClient().getQueryData<Membership[]>(["me", "businesses"]);
  const mine = businesses?.find((b) => b.business_id === businessId);
  const support = mine?.role === SUPPORT_ROLE ? mine : undefined;
  const base = businessId && mine ? `/b/${businessId}` : null;
  const returns = useReturnLinks(businessId ?? "", !!base);

  const show = (item: NavItem) => {
    if (!mine) return false;
    if (item.invoicing && !FEATURES.invoicing) return false;
    if (item.key === "uploads" && !canViewUploads(mine.role)) return false;
    if (item.key === "invoice" && !canCreateDocuments(mine.role)) return false;
    return true;
  };
  const href = (item: NavItem) => {
    if (item.key === "gstr1") return returns.gstr1 ?? `${base}/filing`;
    if (item.key === "w3b") return returns.w3b ?? `${base}/filing`;
    return `${base}${item.path}`;
  };
  const current = base ? currentNav(pathname.slice(base.length), returns) : null;

  const out = async () => {
    await signOut({ rememberPage: false });
    navigate("/signin", { replace: true });
  };

  return (
    <>
      {support && (
        // LLD-2 §6.2: fixed on every screen of a business opened under a grant.
        <p className="banner banner-info support-view" role="status">
          Support view · read-only
          {support.support_ends_at ? ` · ends ${formatDateTimeIst(support.support_ends_at)}` : ""}
        </p>
      )}
      {base && mine && (
        <aside className="side" aria-label="Business">
          <div className="biz">
            <div className="mark" aria-hidden="true">
              {initials(title ?? mine.display_name)}
            </div>
            <div>
              <strong>{title ?? mine.display_name}</strong>
              {(gstin ?? mine.gstin) && <span className="num">{gstin ?? mine.gstin}</span>}
            </div>
          </div>
          <nav aria-label="Main">
            {NAV_GROUPS.map((g) => {
              const items = g.items.filter(show);
              if (!items.length) return null;
              return (
                <div key={g.label} className="side-grp">
                  {g.label !== "Home" && g.label !== "Settings" && <div className="grp">{g.label}</div>}
                  {items.map((item) => (
                    // A plain Link: the shell alone decides which item is current, so GSTR-1 and
                    // GSTR-3B (which fall back to /filing) never light up with Your GST filing.
                    <Link
                      key={item.key}
                      to={href(item)}
                      className="side-link"
                      aria-current={current === item.key ? "page" : undefined}
                    >
                      <Icon d={item.icon} />
                      {item.label}
                    </Link>
                  ))}
                </div>
              );
            })}
          </nav>
        </aside>
      )}
      <header className={base ? "top top-app" : "top"}>
        {base && mine ? (
          <>
            <strong className="bizname">{title ?? mine.display_name}</strong>
            <GlobalSearch businessId={businessId!} />
            <span className="sp" />
            {FEATURES.invoicing && FEATURES.practiceOnly && (
              <span className="practice" title="Invoice numbering is off until your CA confirms it">
                Practice mode
              </span>
            )}
          </>
        ) : (
          <Link to="/" className="top-brand">
            {title && (
              <span className="mark" aria-hidden="true">
                {initials(title)}
              </span>
            )}
            {title && <strong>{title}</strong>}
          </Link>
        )}
        <Button type="button" variant="link" onClick={out}>
          Sign out
        </Button>
      </header>
      {base && mine && (
        <nav className="tabbar" aria-label="Phone">
          {PHONE_TABS.filter(show).map((item) => (
            <Link key={item.key} to={href(item)} aria-current={current && item.covers.includes(current) ? "page" : undefined}>
              <Icon d={item.icon} />
              {item.short}
            </Link>
          ))}
        </nav>
      )}
    </>
  );
}
