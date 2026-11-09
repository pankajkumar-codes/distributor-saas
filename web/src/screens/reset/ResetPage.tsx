import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { api, call } from "../../api/client";
import type { components } from "../../api/schema";
import { errorText, type ApiError } from "../../api/errors";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { Field } from "../../kit/Field";
import { OtpInput } from "../../kit/OtpInput";
import { countdown, useNow } from "../signup/CodeStep";

type CodeSent = components["schemas"]["CodeSent"];
// Step 2 keeps the email in history.state, never the URL (as sign-up does, RM-4.1 row 13), with
// the server's code terms so the countdown and the tries are its numbers, not the web's.
type CodeState = { email: string; sentAt: number; ttlMinutes: number; maxTries: number };
export type ResetDone = { passwordReset: true };

function codeState(state: unknown): CodeState | null {
  const s = state as Partial<CodeState> | null;
  return s && typeof s.email === "string" && typeof s.sentAt === "number" && typeof s.ttlMinutes === "number" && typeof s.maxTries === "number"
    ? (s as CodeState)
    : null;
}

const PASSWORD_HINT =
  "At least 10 characters, with no spaces at the start or end; a few unrelated words work well. Very common passwords aren't accepted.";

/**
 * /reset: forgot password (LLD-1 §5.8). Step 1 asks for the email and always gets the same
 * answer, whether or not an account exists. Step 2 takes the emailed code and a new password.
 * A reset ends every session, so it sets no cookie: the user signs in again.
 */
export function ResetPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const step2 = codeState(location.state);
  const typed = (location.state as { email?: unknown } | null)?.email;
  const [email, setEmail] = useState(typeof typed === "string" ? typed : "");
  const go = (to: string, terms: CodeSent, replace = false) =>
    navigate("/reset", {
      replace,
      state: { email: to, sentAt: Date.now(), ttlMinutes: terms.code_ttl_minutes, maxTries: terms.code_max_tries } satisfies CodeState,
    });

  if (!step2) {
    return <EmailStep email={email} onEmail={setEmail} onSent={(to, terms) => go(to, terms)} />;
  }
  return (
    <CodeStep
      state={step2}
      onResent={(terms) => go(step2.email, terms, true)}
      onBack={() => {
        setEmail(step2.email);
        navigate("/reset", { replace: true, state: null });
      }}
      onDone={() => navigate("/signin", { replace: true, state: { passwordReset: true } satisfies ResetDone })}
    />
  );
}

const send = (email: string) =>
  call(() => api.POST("/api/v1/auth/reset", { body: { email } }), { refresh: false });

function EmailStep({ email, onEmail, onSent }: { email: string; onEmail: (v: string) => void; onSent: (to: string, terms: CodeSent) => void }) {
  const [missing, setMissing] = useState<string>();
  const request = useMutation<CodeSent, ApiError, string>({ mutationFn: send, onSuccess: (terms, to) => onSent(to, terms) });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setMissing(email.trim() ? undefined : "Enter your email.");
    if (email.trim()) request.mutate(email.trim());
  };
  const error = request.error;
  return (
    <main className="page">
      <h1>Reset your password</h1>
      <form onSubmit={submit} noValidate>
        {error && !error.field && <Banner tone="error">{errorText(error)}</Banner>}
        <p>Enter the email you sign in with. If it has an account, we'll email it a code.</p>
        <Field
          label="Email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => onEmail(e.target.value)}
          error={missing ?? (error?.field === "email" ? errorText(error) : undefined)}
        />
        <Button type="submit" busy={request.isPending}>
          Send code
        </Button>
      </form>
      <p className="note">
        <Link to="/signin">Back to sign in</Link>
      </p>
    </main>
  );
}

function CodeStep({ state, onResent, onBack, onDone }: { state: CodeState; onResent: (terms: CodeSent) => void; onBack: () => void; onDone: () => void }) {
  const now = useNow();
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [incomplete, setIncomplete] = useState<{ code?: string; password?: string }>({});

  const verify = useMutation<unknown, ApiError>({
    mutationFn: () =>
      call(() => api.POST("/api/v1/auth/reset/verify", { body: { email: state.email, code, new_password: password } }), { refresh: false }),
    onSuccess: onDone,
  });
  const resend = useMutation<CodeSent, ApiError>({
    mutationFn: () => send(state.email),
    onSuccess: (terms) => {
      setCode("");
      onResent(terms);
    },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const found = { password: password ? undefined : "Choose a new password.", code: code.length < 6 ? "Enter all 6 digits." : undefined };
    setIncomplete(found);
    if (!found.password && !found.code) {
      resend.reset(); // each action clears the other's old error, so a stale one can't mask it
      verify.mutate();
    }
  };

  const error = verify.error ?? resend.error;
  // The password policy names its field "password" (the same check as sign-up).
  const passwordError = incomplete.password ?? (error && ["password", "new_password"].includes(error.field ?? "") ? error.fix ?? errorText(error) : undefined);
  const codeError = incomplete.code ?? (error?.code === "code_not_accepted" ? errorText(error) : undefined);
  const bannerError = error && !error.field && error.code !== "code_not_accepted" ? errorText(error) : undefined;
  const ttl = state.ttlMinutes * 60 * 1000;
  const left = Math.min(ttl, state.sentAt + ttl - now);

  return (
    <main className="page">
      <h1>Check your email</h1>
      <form onSubmit={submit} noValidate>
        {bannerError && <Banner tone="error">{bannerError}</Banner>}
        {resend.isSuccess && !error && <Banner>We sent a new code. Earlier codes no longer work.</Banner>}
        <p>
          If <strong>{state.email}</strong> has an account, we sent it a code. Enter it with your new password.
        </p>
        <OtpInput value={code} onChange={setCode} error={codeError} errorId="code-error" />
        {codeError && (
          <p id="code-error" className="error">
            {codeError}
          </p>
        )}
        <p className="note">{left > 0 ? `Code expires in ${countdown(left)}.` : "This code has expired. Send a new code."}</p>
        <Button
          type="button"
          variant="link"
          busy={resend.isPending}
          onClick={() => {
            verify.reset();
            resend.mutate();
          }}
        >
          Send a new code
        </Button>
        <p className="note">
          The code works for {state.ttlMinutes} minutes. After {state.maxTries} wrong tries it stops working and you can ask for a new one.
        </p>
        <Field
          label="New password"
          type="password"
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          hint={PASSWORD_HINT}
          error={passwordError}
        />
        <p className="note">Changing your password signs you out on every device.</p>
        <div className="actions">
          <Button type="button" variant="link" onClick={onBack}>
            Back
          </Button>
          <Button type="submit" busy={verify.isPending}>
            Set new password
          </Button>
        </div>
      </form>
    </main>
  );
}
