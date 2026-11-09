import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { Field } from "../../kit/Field";
import { NotFound } from "../../kit/NotFound";
import { OtpInput } from "../../kit/OtpInput";
import { TopBar } from "../../kit/TopBar";

type CodeSent = components["schemas"]["CodeSent"];

/**
 * Support › Remove two-step sign-in (LLD-2 §6.3, L2-6; TD-4a). Support enters the account's
 * email; the server mails a code to that address only (and answers the same for any email,
 * so this page never says whether the account exists). The person reads the code out, and
 * support enters it: two-step sign-in is then off for that account and all of its sessions
 * end. The server allows only support staff with two-step sign-in on; anyone else gets 404.
 */
export function TotpRecoveryPage() {
  const [email, setEmail] = useState("");
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [missing, setMissing] = useState<string>();
  const [removedFor, setRemovedFor] = useState<string | null>(null);

  const start = useMutation<CodeSent, ApiError, string>({
    mutationFn: (to) => call(() => api.POST("/api/v1/support/totp-recovery", { body: { email: to } })),
    onSuccess: (_, to) => {
      setSentTo(to);
      setCode("");
    },
  });
  const confirm = useMutation<unknown, ApiError>({
    mutationFn: () => call(() => api.POST("/api/v1/support/totp-recovery/confirm", { body: { email: sentTo ?? "", code } })),
    onSuccess: () => {
      setRemovedFor(sentTo);
      setSentTo(null);
      setEmail("");
      setCode("");
    },
    onError: () => setCode(""),
  });

  if (start.error?.status === 404 || confirm.error?.status === 404) return <NotFound />;

  const send = (e: FormEvent) => {
    e.preventDefault();
    const to = email.trim();
    setMissing(to ? undefined : "Enter the account's email.");
    if (to) {
      setRemovedFor(null);
      start.mutate(to);
    }
  };
  const check = (e: FormEvent) => {
    e.preventDefault();
    const short = code.length < 6 ? "Enter all 6 digits." : undefined;
    setMissing(short);
    if (!short) confirm.mutate();
  };
  const codeError = confirm.error?.code === "code_not_accepted" ? errorText(confirm.error) : missing;
  const terms = start.data;

  return (
    <>
      <TopBar />
      <main className="page">
        <p className="step">
          <Link to="/support">Businesses you can view</Link>
        </p>
        <h1>Remove two-step sign-in</h1>
        <p className="hint">
          For someone who has lost the phone with their authenticator app. We email a code to their account's address;
          they read it to you, and you enter it here.
        </p>
        {removedFor && (
          <Banner>
            Two-step sign-in is off for {removedFor}, and they've been signed out everywhere. We've emailed them to say so.
          </Banner>
        )}

        {!sentTo ? (
          <form onSubmit={send} noValidate>
            {start.error && <Banner tone="error">{errorText(start.error)}</Banner>}
            <Field
              label="Their account email"
              type="email"
              autoComplete="off"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              error={start.error?.field === "email" ? errorText(start.error) : missing}
            />
            <Button type="submit" busy={start.isPending}>
              Email them a code
            </Button>
          </form>
        ) : (
          <form onSubmit={check} noValidate>
            {confirm.error && confirm.error.code !== "code_not_accepted" && (
              <Banner tone="error">{errorText(confirm.error)}</Banner>
            )}
            <p>
              If {sentTo} has two-step sign-in on, we've emailed it a 6-digit code
              {terms ? `. It works for ${terms.code_ttl_minutes} minutes and ${terms.code_max_tries} tries` : ""}. Ask them to
              read it to you. If no email arrives, the account may not exist or may not use two-step sign-in.
            </p>
            <OtpInput value={code} onChange={setCode} error={codeError} errorId="recovery-error" />
            {codeError && (
              <p id="recovery-error" className="error">
                {codeError}
              </p>
            )}
            <div className="actions">
              <Button type="button" variant="link" onClick={() => setSentTo(null)}>
                Start again
              </Button>
              <Button type="submit" busy={confirm.isPending}>
                Remove two-step sign-in
              </Button>
            </div>
          </form>
        )}
      </main>
    </>
  );
}
