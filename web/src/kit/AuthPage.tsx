import type { ReactNode } from "react";

import { APP_NAME } from "../brand";
import { KartaaMark } from "./KartaaMark";

/**
 * The frame of every signed-out page (mocks v16): the brand row, one white card on a light grey
 * page, and the India-only line under it. `wide` is the 720px column used by sign-up.
 */
export function AuthPage({ children, wide = false, busy }: { children: ReactNode; wide?: boolean; busy?: boolean }) {
  return (
    <main className={wide ? "page page-auth page-auth-wide" : "page page-auth"} aria-busy={busy || undefined}>
      <div className="brand">
        <KartaaMark size={28} />
        <b className="wordmark">{APP_NAME}</b>
      </div>
      <div className="auth-card">{children}</div>
      <p className="auth-foot">Your data stays in India.</p>
    </main>
  );
}
