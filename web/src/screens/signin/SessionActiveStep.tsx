import { useMutation } from "@tanstack/react-query";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import { AuthPage } from "../../kit/AuthPage";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import type { SignedIn } from "./SigninPage";

type Props = {
  /** The access token the sign-in answered with. It has no session yet, so it is only good for these two calls. */
  token: string;
  onContinue: (reply: SignedIn) => void;
  onKeepOther: () => void;
  onExpired: () => void;
};

/**
 * One active session per user: the sign-in was right, but the person is signed in on another browser.
 * Yes ends that session and continues here; No leaves it running and this sign-in does not complete.
 */
export function SessionActiveStep({ token, onContinue, onKeepOther, onExpired }: Props) {
  const headers = { Authorization: `Bearer ${token}` };
  const yes = useMutation<SignedIn, ApiError>({
    mutationFn: () => call(() => api.POST("/api/v1/auth/session/replace", { headers }), { refresh: false }),
    onSuccess: onContinue,
    onError: (error) => {
      if (error.code === "session_invalid") onExpired(); // too long since the sign-in: start again
    },
  });
  const no = useMutation<void, ApiError>({
    // Always answers 204, and the person's wish is the same whether or not it got through.
    mutationFn: () => call(() => api.POST("/api/v1/auth/session/cancel", { headers }), { refresh: false }),
    onSettled: onKeepOther,
  });
  const busy = yes.isPending || no.isPending;
  return (
    <AuthPage>
      <h1>One session is already active</h1>
      <div className="card stack">
        {yes.error && yes.error.code !== "session_invalid" && <Banner tone="error">{errorText(yes.error)}</Banner>}
        <p>One session is already active. Sign out there and continue here?</p>
        <Button type="button" busy={yes.isPending} disabled={busy} className="btn-block" onClick={() => yes.mutate()}>
          Yes, sign out there and continue here
        </Button>
        <Button type="button" variant="secondary" busy={no.isPending} disabled={busy} className="btn-block" onClick={() => no.mutate()}>
          No, keep the other session
        </Button>
      </div>
    </AuthPage>
  );
}
