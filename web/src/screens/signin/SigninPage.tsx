import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { api, call } from "../../api/client";
import type { components } from "../../api/schema";
import { errorText, type ApiError } from "../../api/errors";
import { safeNext } from "../../auth/AuthProvider";
import { landingPath } from "../../auth/landing";
import { startSession } from "../../auth/session";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { Field } from "../../kit/Field";
import { TotpStep } from "./TotpStep";

export type SignedIn = components["schemas"]["SignedInOut"];
type SigninReply = SignedIn | components["schemas"]["TotpStepOut"];

/**
 * /signin, then the authenticator-app step on the same URL. The TOTP challenge and the
 * email stay in component memory only: a reload starts sign-in again rather than keep the
 * provider's session string anywhere the browser persists (LLD-1 L1-7).
 */
export function SigninPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [challenge, setChallenge] = useState<string | null>(null);
  const [expired, setExpired] = useState(false);
  const [missing, setMissing] = useState<{ email?: string; password?: string }>({});

  const done = (reply: SignedIn) => {
    startSession(reply.access_token, reply.expires_in);
    navigate(safeNext(params.get("next")) ?? landingPath(reply.memberships), { replace: true });
  };

  const signin = useMutation<SigninReply, ApiError>({
    mutationFn: () =>
      call(() => api.POST("/api/v1/auth/signin", { body: { email: email.trim(), password } }), {
        refresh: false,
      }),
    onMutate: () => setExpired(false),
    onSuccess: (reply) => {
      setPassword(""); // not needed past this point
      if ("step" in reply) setChallenge(reply.challenge);
      else done(reply);
    },
  });

  if (challenge) {
    return (
      <TotpStep
        email={email.trim()}
        challenge={challenge}
        onChallenge={setChallenge}
        onDone={done}
        onExpired={() => {
          setChallenge(null);
          setExpired(true);
        }}
      />
    );
  }

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const empty = {
      email: email.trim() ? undefined : "Enter your email.",
      password: password ? undefined : "Enter your password.",
    };
    setMissing(empty);
    if (!empty.email && !empty.password) signin.mutate();
  };

  const error = signin.error;
  return (
    <main className="page">
      <h1>Sign in</h1>
      <form onSubmit={submit} noValidate>
        {expired && <Banner tone="error">That took too long. Sign in again.</Banner>}
        {error && !error.field && <Banner tone="error">{errorText(error)}</Banner>}
        <Field
          label="Email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          error={missing.email ?? (error?.field === "email" ? errorText(error) : undefined)}
        />
        <Field
          label="Password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          error={missing.password}
        />
        <Button type="submit" busy={signin.isPending}>
          Sign in
        </Button>
      </form>
      <p className="note">
        New here? <Link to="/signup">Create an account</Link>
      </p>
    </main>
  );
}
