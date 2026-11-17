import { isDemo } from "../demo";
import { Banner } from "./Banner";

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

/** The same for two-step sign-in: the demo's code is not the one an authenticator app shows. */
export function DemoTwoStepNote() {
  if (!isDemo()) return null;
  return (
    <Banner>
      Local demo: an authenticator app will not show the right code here. Use the 6-digit TWO-STEP CODE printed in the
      terminal window where you started the demo. If you closed it, run ./demo.sh codes (or .\demo.ps1 codes on
      Windows).
    </Banner>
  );
}
