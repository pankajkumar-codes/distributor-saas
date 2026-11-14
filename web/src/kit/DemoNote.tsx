import { Banner } from "./Banner";

/** True only in the local demo's web build (demo/Dockerfile sets VITE_DEMO); a production build never has it. */
export const isDemo = () => import.meta.env.VITE_DEMO === "1";

/** Tells a person trying the local demo where the sign-up code is, because the demo sends no email. */
export function DemoNote() {
  if (!isDemo()) return null;
  return (
    <Banner>
      Local demo: no email is sent. The 6-digit code is printed in the terminal window where you started the demo. If
      you closed it, run ./demo.sh codes (or .\demo.ps1 codes on Windows).
    </Banner>
  );
}
