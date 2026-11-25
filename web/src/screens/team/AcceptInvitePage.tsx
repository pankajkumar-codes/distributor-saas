import { useEffect } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { errorText } from "../../api/errors";
import { useAuthStatus } from "../../auth/AuthProvider";
import { AuthPage } from "../../kit/AuthPage";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { useAcceptInvite, useInvitePreview } from "./useTeam";
import { Loading } from "../../kit/Loading";

const ROLE_LABEL: Record<string, string> = { owner: "an owner", admin: "an admin", billing: "billing", ca: "a CA" };

/**
 * The page the invitation email links to (/invite/:token). It is matched on the email of the account you are signed in
 * with, so a link opened by someone else, or after it was replaced or has expired, looks the same as no invitation.
 * New people create an account first, then open the link again.
 */
export function AcceptInvitePage() {
  const { token = "" } = useParams();
  const status = useAuthStatus();
  const navigate = useNavigate();
  const signedIn = status === "signed_in";
  const preview = useInvitePreview(token, signedIn);
  const accept = useAcceptInvite(token);

  useEffect(() => {
    if (accept.data) navigate(`/b/${accept.data.business_id}/home`, { replace: true });
  }, [accept.data, navigate]);

  if (status === "checking") {
    return (
      <AuthPage busy>
        <p>Loading…</p>
      </AuthPage>
    );
  }
  if (status === "unavailable") {
    return (
      <AuthPage>
        <Banner tone="error">We couldn't reach the server. Check your connection and try again.</Banner>
      </AuthPage>
    );
  }
  const here = `/invite/${token}`;
  if (!signedIn) {
    return (
      <AuthPage>
        <h1>You have been invited</h1>
        <p>Sign in with the email address this invitation was sent to, then come back to this page to accept it.</p>
        <p>
          <Link className="btn btn-primary" to={`/signin?next=${encodeURIComponent(here)}`}>
            Sign in
          </Link>
        </p>
        <p>
          New here? <Link to="/signup">Create an account</Link> with the same email address, then open the link in your email again.
        </p>
      </AuthPage>
    );
  }
  return (
    <AuthPage>
      <h1>You have been invited</h1>
      {preview.isPending && <Loading query={preview} />}
      {preview.error?.status === 404 && (
        <Banner tone="error">
          This invitation isn't available to this account. It may have expired, been replaced by a newer one, or been sent to a different email address. Sign in with the
          invited email, or ask for a new invitation.
        </Banner>
      )}
      {preview.error && preview.error.status !== 404 && <Banner tone="error">{errorText(preview.error)}</Banner>}
      {preview.data && (
        <>
          <p>
            {preview.data.inviter_name ?? "Someone"} invited you to join <strong>{preview.data.business_name ?? "a business"}</strong> as {ROLE_LABEL[preview.data.role] ?? preview.data.role}.
          </p>
          {accept.error && <Banner tone="error">{accept.error.fix ?? (accept.error.message || errorText(accept.error))}</Banner>}
          <Button type="button" busy={accept.isPending} onClick={() => accept.mutate()}>
            Accept the invitation
          </Button>
        </>
      )}
      <p>
        <Link to="/businesses">Your businesses</Link>
      </p>
    </AuthPage>
  );
}
