import { useMutation } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import { tokenStore } from "../../auth/tokenStore";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { Field } from "../../kit/Field";
import { OtpInput } from "../../kit/OtpInput";

// The verify route has no response model yet, so the generated type is `unknown`.
type Verified = { access_token: string; expires_in: number };

const CODE_TTL_MS = 10 * 60 * 1000; // auth.code_ttl_minutes; the server decides, this is the countdown

type Props = {
  email: string;
  sentAt: number;
  password: string;
  onResent: (sentAt: number) => void;
  onBack: () => void;
  onPasswordChange: (password: string) => void;
};

function useNow() {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  return now;
}

function countdown(ms: number) {
  const s = Math.ceil(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function CodeStep({ email, sentAt, password, onResent, onBack, onPasswordChange }: Props) {
  const navigate = useNavigate();
  const now = useNow();
  const [code, setCode] = useState("");
  const [incomplete, setIncomplete] = useState<string>();
  // After a reload the password is gone [RM41-12]: ask for it again rather than start over.
  const [reloaded] = useState(password === "");

  const verify = useMutation<Verified, ApiError>({
    mutationFn: () =>
      call(api.POST("/api/v1/auth/signup/verify", { body: { email, code, password } })) as Promise<Verified>,
    onSuccess: (done) => {
      tokenStore.set(done.access_token, done.expires_in);
      navigate("/onboarding/business", { replace: true }); // drops the entry holding the email
    },
  });
  const resend = useMutation<unknown, ApiError>({
    mutationFn: () => call(api.POST("/api/v1/auth/signup", { body: { email } })),
    onSuccess: () => {
      setCode("");
      verify.reset();
      onResent(Date.now());
    },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const missing = !password ? "Enter your password." : code.length < 6 ? "Enter all 6 digits." : undefined;
    setIncomplete(missing);
    if (!missing) verify.mutate();
  };

  const error = verify.error ?? resend.error;
  const passwordError = error?.field === "password" ? errorText(error) : !password ? incomplete : undefined;
  const codeError = error?.code === "code_not_accepted" ? errorText(error) : password ? incomplete : undefined;
  const bannerError = error && !error.field && error.code !== "code_not_accepted" ? errorText(error) : undefined;
  const left = Math.min(CODE_TTL_MS, sentAt + CODE_TTL_MS - now);

  return (
    <main className="page">
      <p className="step">Step 2 of 4</p>
      <h1>Check your email</h1>
      <form onSubmit={submit} noValidate>
        {bannerError && <Banner tone="error">{bannerError}</Banner>}
        {resend.isSuccess && !error && <Banner>We sent a new code. Earlier codes no longer work.</Banner>}
        <p>
          Enter the code we sent to <strong>{email}</strong>.
        </p>
        {(reloaded || error?.field === "password") && (
          <Field
            label="Password"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => onPasswordChange(e.target.value)}
            hint={reloaded ? "Enter your password again. We don't keep it when the page reloads." : undefined}
            error={passwordError}
          />
        )}
        <OtpInput value={code} onChange={setCode} error={codeError} errorId="code-error" />
        {codeError && (
          <p id="code-error" className="error">
            {codeError}
          </p>
        )}
        <p className="note">
          {left > 0 ? `Code expires in ${countdown(left)}.` : "This code has expired. Send a new code."}
        </p>
        <Button type="button" variant="link" busy={resend.isPending} onClick={() => resend.mutate()}>
          Send a new code
        </Button>
        <p className="note">The code works for 10 minutes. After 5 wrong tries it stops working and you can ask for a new one.</p>
        <div className="actions">
          <Button type="button" variant="link" onClick={onBack}>
            Back
          </Button>
          <Button type="submit" busy={verify.isPending}>
            Create account
          </Button>
        </div>
      </form>
    </main>
  );
}
