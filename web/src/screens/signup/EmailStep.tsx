import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { DemoNote } from "../../kit/DemoNote";
import { Field } from "../../kit/Field";
import { PasswordRules } from "../../kit/PasswordRules";

type Props = { initialEmail: string; initialPassword: string; onSent: (email: string, password: string) => void };

export function EmailStep({ initialEmail, initialPassword, onSent }: Props) {
  const [email, setEmail] = useState(initialEmail);
  const [password, setPassword] = useState(initialPassword);
  const [missing, setMissing] = useState<{ email?: string; password?: string }>({});
  const send = useMutation<unknown, ApiError, string>({
    mutationFn: (to) => call(() => api.POST("/api/v1/auth/signup", { body: { email: to, password } }), { refresh: false }),
    onSuccess: (_, to) => onSent(to, password),
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const empty = {
      email: email.trim() ? undefined : "Enter your work email.",
      password: password ? undefined : "Choose a password.",
    };
    setMissing(empty);
    if (!empty.email && !empty.password) send.mutate(email.trim());
  };

  const error = send.error;
  const emailError = missing.email ?? (error?.field === "email" ? errorText(error) : undefined);

  return (
    <main className="page">
      <p className="step">Step 1 of 4</p>
      <h1>Create your account</h1>
      <form onSubmit={submit} noValidate>
        <DemoNote />
        {error && !error.field && <Banner tone="error">{errorText(error)}</Banner>}
        <Field
          label="Work email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          error={emailError}
        />
        <Field label="Mobile number" type="tel" disabled hint="Sign-up by mobile is coming later" />
        <Field
          label="Password"
          type="password"
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          error={missing.password ?? (error?.field === "password" ? errorText(error) : undefined)}
        />
        <PasswordRules unmet={error?.field === "password" ? error.unmet : undefined} />
        <p className="note">
          We email you a 6-digit code to confirm the address. If this email already has an account, you see this same
          message.
        </p>
        <Button type="submit" busy={send.isPending}>
          Email me a code
        </Button>
      </form>
    </main>
  );
}
