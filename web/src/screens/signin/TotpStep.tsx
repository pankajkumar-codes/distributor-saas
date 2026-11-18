import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import { AuthPage } from "../../kit/AuthPage";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { DemoTwoStepNote } from "../../kit/DemoNote";
import { OtpInput } from "../../kit/OtpInput";
import type { SigninReply } from "./SigninPage";

type Props = {
  email: string;
  challenge: string;
  onChallenge: (challenge: string) => void;
  onDone: (reply: SigninReply) => void;
  onExpired: () => void;
};

export function TotpStep({ email, challenge, onChallenge, onDone, onExpired }: Props) {
  const [code, setCode] = useState("");
  const [incomplete, setIncomplete] = useState<string>();
  const totp = useMutation<SigninReply, ApiError>({
    mutationFn: () =>
      call(() => api.POST("/api/v1/auth/signin/totp", { body: { email, challenge, code } }), {
        refresh: false,
      }),
    onSuccess: onDone,
    onError: (error) => {
      if (error.code === "signin_expired") onExpired();
      else if (error.challenge) onChallenge(error.challenge); // the provider may issue a new one per try
      setCode("");
    },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const missing = code.length < 6 ? "Enter all 6 digits." : undefined;
    setIncomplete(missing);
    if (!missing) totp.mutate();
  };

  const error = totp.error;
  const codeError = error?.code === "totp_not_accepted" ? errorText(error) : incomplete;
  return (
    <AuthPage>
      <h1>Two-step sign-in</h1>
      <form onSubmit={submit} noValidate className="card stack">
        {error && error.code !== "totp_not_accepted" && <Banner tone="error">{errorText(error)}</Banner>}
        <DemoTwoStepNote />
        <p>Enter the 6-digit code from your authenticator app.</p>
        <OtpInput value={code} onChange={setCode} error={codeError} errorId="totp-error" />
        {codeError && (
          <p id="totp-error" className="error">
            {codeError}
          </p>
        )}
        <Button type="submit" busy={totp.isPending} className="btn-block">
          Sign in
        </Button>
        {/* RM2-29, the PO's words; support removes it after an email-code check (LLD-2 §6.3). */}
        <p className="hint">Lost your phone? Contact support.</p>
      </form>
    </AuthPage>
  );
}
