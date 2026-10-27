import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { OtpInput } from "../../kit/OtpInput";
import type { SignedIn } from "./SigninPage";

type Props = {
  email: string;
  challenge: string;
  onChallenge: (challenge: string) => void;
  onDone: (reply: SignedIn) => void;
  onExpired: () => void;
};

export function TotpStep({ email, challenge, onChallenge, onDone, onExpired }: Props) {
  const [code, setCode] = useState("");
  const [incomplete, setIncomplete] = useState<string>();
  const totp = useMutation<SignedIn, ApiError>({
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
    <main className="page">
      <h1>Two-step sign-in</h1>
      <form onSubmit={submit} noValidate>
        {error && error.code !== "totp_not_accepted" && <Banner tone="error">{errorText(error)}</Banner>}
        <p>Enter the 6-digit code from your authenticator app.</p>
        <OtpInput value={code} onChange={setCode} error={codeError} errorId="totp-error" />
        {codeError && (
          <p id="totp-error" className="error">
            {codeError}
          </p>
        )}
        <Button type="submit" busy={totp.isPending}>
          Sign in
        </Button>
      </form>
    </main>
  );
}
