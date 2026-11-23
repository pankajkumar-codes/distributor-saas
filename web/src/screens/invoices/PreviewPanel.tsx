import { useLocation, useNavigate } from "react-router-dom";

import { errorText } from "../../api/errors";
import { signOut } from "../../auth/session";
import { isDemo } from "../../demo";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import type { usePreview } from "./usePreview";

/**
 * The PDF preview of the saved draft, in its five states: idle (button only), preparing, ready (link), slow (over 30 seconds,
 * with Try again) and session ended (Sign in again, back to this same draft; the draft is saved on the server, so nothing is lost).
 */
export function PreviewPanel({ preview, version, dirty }: { preview: ReturnType<typeof usePreview>; version: number; dirty: boolean }) {
  const navigate = useNavigate();
  const here = useLocation().pathname;
  // A preview of an older version is not shown for this one.
  const current = preview.forVersion === undefined || preview.forVersion === version;
  const state = current ? preview.state : "idle";
  const signInAgain = async () => {
    await signOut();
    navigate(`/signin?next=${encodeURIComponent(here)}`, { replace: true });
  };
  // The PDF renderer runs only in the cloud (D-042); the local demo records the request and nothing ever draws it,
  // so the button would only wait and then say "taking longer than usual". Say so up front instead.
  if (isDemo())
    return (
      <section aria-label="Preview">
        <Button type="button" disabled>
          Preview PDF
        </Button>
        <p className="hint">PDF previews aren't made in the local demo: the PDF maker runs only in the cloud. Your draft is saved.</p>
      </section>
    );
  return (
    <section aria-label="Preview">
      <Button type="button" busy={preview.start.isPending} disabled={dirty} onClick={() => preview.start.mutate()}>
        Preview PDF
      </Button>
      {dirty && <p className="hint">Save first: the preview shows the saved draft.</p>}
      {state === "preparing" && <p aria-busy="true">Preparing the preview…</p>}
      {state === "slow" && (
        <Banner tone="info">
          The preview is taking longer than usual. Your draft is saved.{" "}
          <Button type="button" variant="link" onClick={preview.retry}>
            Try again
          </Button>
        </Banner>
      )}
      {state === "failed" && (
        <Banner tone="error">
          The preview could not be made.{" "}
          <Button type="button" variant="link" onClick={preview.retry}>
            Try again
          </Button>
        </Banner>
      )}
      {state === "error" && preview.error && (
        <Banner tone="error">
          {errorText(preview.error)}{" "}
          <Button type="button" variant="link" onClick={preview.retry}>
            Try again
          </Button>
        </Banner>
      )}
      {state === "ended" && (
        <Banner tone="error">
          Your session has ended. Your draft is saved.{" "}
          <Button type="button" variant="link" onClick={signInAgain}>
            Sign in again
          </Button>
        </Banner>
      )}
      {state === "ready" && (
        <p>
          <a href={preview.status.data?.url ?? "#"} target="_blank" rel="noopener noreferrer">
            Open the preview (PDF)
          </a>{" "}
          <span className="hint">Draft, not a tax invoice.</span>
        </p>
      )}
    </section>
  );
}
