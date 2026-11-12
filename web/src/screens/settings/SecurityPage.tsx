import { useMutation, useQueryClient } from "@tanstack/react-query";
import QRCode from "qrcode";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import { signOut } from "../../auth/session";
import { TOTP_PROMPTED, useMe } from "../../auth/useMe";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { APP_NAME } from "../../brand";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { NotFound } from "../../kit/NotFound";
import { OtpInput } from "../../kit/OtpInput";
import { TopBar } from "../../kit/TopBar";

/** The key URI authenticator apps read (LLD-1 §5.9): issuer and account in the label, issuer again as a parameter. */
export function otpauthUri(secret: string, email: string, issuer = APP_NAME): string {
  const enc = encodeURIComponent;
  return `otpauth://totp/${enc(issuer)}:${enc(email)}?secret=${enc(secret)}&issuer=${enc(issuer)}`;
}

/** The secret in groups of four, easier to type into an app by hand. */
export const grouped = (secret: string) => secret.replace(/(.{4})(?=.)/g, "$1 ");

/**
 * Settings › Two-step sign-in (LLD-1 §5.9, §11.2; TD-4a). Off by default for everyone; owners
 * and CAs are asked to turn it on. Turning on: the server makes a secret, the page draws it as
 * a QR code here (the secret never leaves the page and isn't kept), and one code from the app
 * confirms it. Turning off needs a sign-in in the last few minutes: the server says
 * `reauth_required` otherwise, and the page sends the user to sign in again and back here.
 *
 * Under a business (/b/:id/settings/security) for members, and at /account/security for
 * support staff, who have no business of their own and must turn it on first (L2-5).
 */
export function SecurityPage() {
  const { businessId } = useParams();
  const businesses = useMyBusinesses();
  const business = businessId ? businesses.data?.find((b) => b.business_id === businessId) : undefined;
  const me = useMe();
  const client = useQueryClient();
  const navigate = useNavigate();
  const here = useLocation().pathname;

  const [secret, setSecret] = useState<string | null>(null);
  const [qr, setQr] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [incomplete, setIncomplete] = useState<string>();
  const [asking, setAsking] = useState(false); // "Turn it off?" shown
  const [done, setDone] = useState<"on" | "off" | null>(null);

  const refreshMe = () => client.invalidateQueries({ queryKey: ["me"] });
  // 409 totp_already_on / totp_already_off: another tab changed it; show what is true now.
  const stale = (e: ApiError) => {
    if (e.code === "totp_already_on" || e.code === "totp_already_off") {
      forget();
      setAsking(false);
      refreshMe();
    }
  };

  const setup = useMutation<{ secret: string }, ApiError>({
    mutationFn: () => call(() => api.POST("/api/v1/me/totp/setup")),
    gcTime: 0, // the reply holds the secret: never keep it in the cache once the page is gone
    onSuccess: (r) => {
      setSecret(r.secret);
      setCode("");
      setDone(null);
    },
    onError: stale,
  });
  // The secret lives only in this page's state and the setup reply: drop both together.
  function forget() {
    setSecret(null);
    setup.reset();
  }
  const confirm = useMutation<unknown, ApiError>({
    mutationFn: () => call(() => api.POST("/api/v1/me/totp/confirm", { body: { code } })),
    onSuccess: () => {
      forget();
      setDone("on");
      refreshMe();
    },
    onError: (e) => {
      setCode("");
      stale(e);
    },
  });
  const remove = useMutation<unknown, ApiError>({
    mutationFn: () => call(() => api.DELETE("/api/v1/me/totp")),
    onSuccess: () => {
      setAsking(false);
      setDone("off");
      refreshMe();
    },
    onError: stale,
  });

  const email = me.data?.user.email ?? "";
  useEffect(() => {
    if (!secret) {
      setQr(null);
      return;
    }
    let live = true;
    QRCode.toString(otpauthUri(secret, email), { type: "svg", margin: 1, errorCorrectionLevel: "M" }).then(
      (svg) => live && setQr(`data:image/svg+xml;utf8,${encodeURIComponent(svg)}`),
      () => live && setQr(null), // the secret below still works
    );
    return () => {
      live = false;
    };
  }, [secret, email]);

  if (businessId) {
    if (businesses.isPending) return <Loading />;
    if (!business) return <NotFound />;
  }
  if (me.isPending) return <Loading />;
  if (me.error) {
    return (
      <main className="page">
        <Banner tone="error">{errorText(me.error)}</Banner>
      </main>
    );
  }
  const on = me.data.user.totp_enabled;
  const prompted = business ? TOTP_PROMPTED.has(business.role) : me.data.user.is_support;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const missing = code.length < 6 ? "Enter all 6 digits." : undefined;
    setIncomplete(missing);
    if (!missing) confirm.mutate();
  };
  const signInAgain = async () => {
    await signOut();
    navigate(`/signin?next=${encodeURIComponent(here)}`, { replace: true });
  };
  const codeError = confirm.error?.code === "totp_not_accepted" ? errorText(confirm.error) : incomplete;
  const otherError = [setup.error, confirm.error, remove.error].find(
    (e) => e && !["totp_not_accepted", "reauth_required", "totp_already_on", "totp_already_off"].includes(e.code),
  );

  return (
    <>
      <TopBar title={business?.display_name} gstin={business?.gstin} />
      <main className="page">
        <p className="step">
          <Link to={business ? `/b/${business.business_id}/home` : "/support"}>{business ? "Home" : "Businesses you can view"}</Link>
        </p>
        <h1>Two-step sign-in</h1>
        <p className="hint">
          With it on, signing in asks for your password and a 6-digit code from an authenticator app on your phone, so a
          stolen password alone can't open your account.
        </p>
        {otherError && <Banner tone="error">{errorText(otherError)}</Banner>}
        {done === "on" && <Banner>Two-step sign-in is on. You'll need your authenticator app each time you sign in.</Banner>}
        {done === "off" && <Banner>Two-step sign-in is off.</Banner>}

        {on && (
          <section className="card" aria-labelledby="totp-on">
            <h2 id="totp-on">On</h2>
            <p>Signing in asks for a code from your authenticator app.</p>
            {remove.error?.code === "reauth_required" ? (
              <Banner>
                To turn it off, sign in again first. It's a check that it's really you.{" "}
                <Button type="button" variant="link" onClick={signInAgain}>
                  Sign in again
                </Button>
              </Banner>
            ) : asking ? (
              <>
                <p>Turning it off makes your account easier to break into. Turn it off?</p>
                <div className="actions">
                  <Button type="button" variant="link" onClick={() => setAsking(false)}>
                    Keep it on
                  </Button>
                  <Button type="button" busy={remove.isPending} onClick={() => remove.mutate()}>
                    Yes, turn it off
                  </Button>
                </div>
              </>
            ) : (
              <Button type="button" variant="link" onClick={() => setAsking(true)}>
                Turn off two-step sign-in
              </Button>
            )}
          </section>
        )}

        {!on && !secret && (
          <section className="card" aria-labelledby="totp-off">
            <h2 id="totp-off">Off</h2>
            {prompted && (
              <p>
                {business
                  ? "You can see this business's invoices and filings. We recommend turning this on."
                  : "Support staff must turn this on before they can view any business."}
              </p>
            )}
            <p className="hint">You'll need an authenticator app, such as Google Authenticator or Microsoft Authenticator.</p>
            <Button type="button" busy={setup.isPending} onClick={() => setup.mutate()}>
              Turn on two-step sign-in
            </Button>
          </section>
        )}

        {!on && secret && (
          <section className="card" aria-labelledby="totp-setup">
            <h2 id="totp-setup">Scan this code</h2>
            <p>Open your authenticator app, add an account, and scan this code.</p>
            {qr && <img className="qr" src={qr} alt="QR code for your authenticator app" width={200} height={200} />}
            <p className="hint">
              Can't scan it? Enter this key in the app instead: <code>{grouped(secret)}</code>
            </p>
            <form onSubmit={submit} noValidate>
              <p>Then enter the 6-digit code the app shows.</p>
              <OtpInput value={code} onChange={setCode} error={codeError} errorId="totp-error" />
              {codeError && (
                <p id="totp-error" className="error">
                  {codeError}
                </p>
              )}
              <div className="actions">
                <Button type="button" variant="link" onClick={() => forget()}>
                  Cancel
                </Button>
                <Button type="submit" busy={confirm.isPending}>
                  Turn on
                </Button>
              </div>
            </form>
          </section>
        )}
      </main>
    </>
  );
}

function Loading() {
  return (
    <main className="page" aria-busy="true">
      <p>Loading…</p>
    </main>
  );
}
