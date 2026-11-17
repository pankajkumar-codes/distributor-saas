import { useEffect, useState } from "react";

import { errorText } from "../../api/errors";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { useExportStatus, useStartExport, type ExportStatus } from "./export";
import { PortalGuide } from "./PortalGuide";
import type { ReturnDetail } from "./returns";

/** What a person reads for each reason the file could not be made (the job's code). */
const FAILED: Record<string, string> = {
  changed_during_export: "The return changed while the file was being made. Check it and try again.",
  not_ready: "The return is no longer ready. Look at the items above and try again.",
  nothing_to_file: "There is nothing in this return to put in a file.",
  not_renderable: "We can't make a file for this kind of return yet.",
  file_too_large: "The file came out too large for the portal. Contact support.",
  not_allowed: "Your role can't make this file.",
};

/** What the file holds, how to use it and what it does not say: shared by a new file and a kept one. */
export function FileResult({ file, title }: { file: ExportStatus; title: string }) {
  return (
    <div className="stack">
      <h3>{title}</h3>
      <ul>
        {file.files.map((f) => (
          <li key={f.part}>
            <a href={f.url} download>
              {file.files.length === 1 ? "Download the file" : `Download part ${f.part} of ${file.files.length}`}
            </a>{" "}
            <span className="hint">
              {f.rows === 1 ? "1 row" : `${f.rows} rows`}. This link works for a minute; ask again if it has expired.
            </span>
          </li>
        ))}
      </ul>
      {file.ready_to_upload ? (
        <Banner>This file has been checked against the GST portal.</Banner>
      ) : (
        <Banner tone="error">
          {file.portal_tested
            ? "Not every table in this file has been checked against the GST portal."
            : "This file has not been through the GST portal yet."}{" "}
          Upload it there and check what the portal says before you rely on it.
          {file.unverified_tables.length > 0 && <> We are least sure of these tables: {file.unverified_tables.map((t) => t.toUpperCase()).join(", ")}.</>}
        </Banner>
      )}
      {file.not_in_file.length > 0 && (
        <p className="hint">
          Not in this file, so enter on the portal: {file.not_in_file.join("; ")}.
        </p>
      )}
    </div>
  );
}

/**
 * Make the GSTR-1 file (R1-M8 S6). The button is off, with the reason beside it, while the server's gate says no; once
 * pressed the file is made in the background and this panel asks until it is done. Nothing here says "ready to upload"
 * unless the server says the file is.
 */
export function ExportPanel({ businessId, instanceId, gate, fingerprint, periodLabel }: { businessId: string; instanceId: string; gate: ReturnDetail["export"]; fingerprint: string; periodLabel: string }) {
  const [jobId, setJobId] = useState<string | null>(null);
  const start = useStartExport(businessId, instanceId);
  const status = useExportStatus(businessId, instanceId, jobId);
  const [madeFor, setMadeFor] = useState<string | null>(null);
  useEffect(() => {
    if (jobId !== null && madeFor !== null && madeFor !== fingerprint) setJobId(null); // the return moved on: the old file is not this return's
  }, [fingerprint, jobId, madeFor]);

  const s = status.data;
  const busy = start.isPending || s?.status === "preparing";
  return (
    <section className="card" aria-labelledby="file">
      <h2 id="file">Your GSTR-1 file</h2>
      {!gate.ready && (
        <div className="stack">
          {gate.reasons.map((r) => (
            <Banner tone="error" key={r.code}>
              {r.message}
            </Banner>
          ))}
          {gate.to_accept > 0 && <p>{gate.to_accept === 1 ? "1 warning still needs" : `${gate.to_accept} warnings still need`} you to accept {gate.to_accept === 1 ? "it" : "them"} as shown. Open the check above and choose “Accept as shown”.</p>}
        </div>
      )}
      {gate.ready && !s && <p>The checks are done. Make the file for the GST portal from this return as it is now.</p>}
      <Button
        busy={busy}
        disabled={!gate.ready}
        onClick={() =>
          start.mutate(undefined, {
            onSuccess: (r) => {
              setJobId(r.job_id);
              setMadeFor(fingerprint);
            },
          })
        }
      >
        {busy ? "Making your file…" : s?.status === "ready" ? "Make the file again" : "Make my GSTR-1 file"}
      </Button>
      {start.isError && <Banner tone="error">{errorText(start.error)}</Banner>}
      {status.isError && <Banner tone="error">We couldn't check on your file. {errorText(status.error)}</Banner>}
      {s?.status === "failed" && <Banner tone="error">{FAILED[s.error_code ?? ""] ?? "We couldn't make the file. Try again, or contact support."}</Banner>}
      {s?.status === "ready" && <FileResult file={s} title={`Your file (version ${s.version})`} />}
      {s?.status === "ready" && <PortalGuide periodLabel={periodLabel} readyToUpload={s.ready_to_upload} />}
    </section>
  );
}
