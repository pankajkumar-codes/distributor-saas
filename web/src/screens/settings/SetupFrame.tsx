import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { TopBar } from "../../kit/TopBar";

type Business = { display_name: string; gstin?: string | null };

/**
 * The page chrome of a settings part. On its own route a part is a whole page (top bar, main);
 * inside Business setup it is only its body, so the page has one top bar and one main.
 */
export function SetupFrame({ embedded, business, busy, children }: { embedded?: boolean; business?: Business; busy?: boolean; children: ReactNode }) {
  if (embedded) return <div aria-busy={busy || undefined}>{children}</div>;
  return (
    <>
      {business && <TopBar title={business.display_name} gstin={business.gstin} />}
      <main className="page" aria-busy={busy || undefined}>
        {children}
      </main>
    </>
  );
}

/** The part's title: a page heading on its own route, a section heading inside Business setup. */
export function SetupTitle({ embedded, businessId, title }: { embedded?: boolean; businessId: string; title: string }) {
  if (embedded) return <h2 className="setup-h">{title}</h2>;
  return (
    <>
      <p className="step">
        <Link to={`/b/${businessId}/home`}>Home</Link>
      </p>
      <h1>{title}</h1>
    </>
  );
}
