import type { ReactNode } from "react";

import { APP_NAME } from "../brand";

/** The frame of every signed-out page: the brand row above one column. `wide` is the 720px column. */
export function AuthPage({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  return (
    <main className={wide ? "page page-auth page-auth-wide" : "page page-auth"}>
      <div className="brand">
        <span className="mark" aria-hidden="true">
          {APP_NAME.split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase()}
        </span>
        <b>{APP_NAME}</b>
      </div>
      {children}
    </main>
  );
}
