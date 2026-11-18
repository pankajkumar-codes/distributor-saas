import type { ReactNode } from "react";

import { APP_NAME } from "../brand";
import { KartaaMark } from "./KartaaMark";

/** The frame of every signed-out page: the brand row above one column. `wide` is the 720px column. */
export function AuthPage({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  return (
    <main className={wide ? "page page-auth page-auth-wide" : "page page-auth"}>
      <div className="brand">
        <KartaaMark size={32} />
        <b className="wordmark">{APP_NAME}</b>
      </div>
      {children}
    </main>
  );
}
