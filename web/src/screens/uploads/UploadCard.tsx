import { useId, useRef, useState, type FormEvent } from "react";

import { errorText } from "../../api/errors";
import { formatDateTimeIst } from "../../format/dates";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { acceptFor, settled, sectionChip, statusText, wrongType, SECTIONS, type Section, type Upload } from "./sections";
import { Panel } from "../filing/ledger";
import { HeldLink } from "./HeldLink";
import { useStartUpload, useUpload, useUploads } from "./useUpload";

type Props = {
  businessId: string;
  section: Section;
  label: string;
  hint: string;
  canUpload: boolean;
  /** The upload this card follows (kept by the page, in the URL, so a reload resumes). */
  uploadId: string | null;
  onUpload: (uploadId: string | null) => void;
};

/**
 * One section's upload: choose a file, send it, and watch the server read it. The server decides
 * everything about the file (type, size, layout, whose GSTIN it carries) and answers in words;
 * the card only shows those words. Sections are optional, so a card with nothing uploaded is fine.
 */
export function UploadCard({ businessId, section, label, hint, canUpload, uploadId, onUpload }: Props) {
  const id = useId();
  const choice = SECTIONS.find((s) => s.id === section) ?? SECTIONS[0];
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [problem, setProblem] = useState<string>();
  const start = useStartUpload(businessId, (started) => {
    setFile(null);
    if (input.current) input.current.value = "";
    onUpload(started);
  });
  const current = useUpload(businessId, uploadId);
  const recent = useUploads(businessId, section);

  const choose = (picked: File | undefined) => {
    start.reset();
    start.newChoice(); // a different file is a different upload
    setFile(picked ?? null);
    setProblem(picked && wrongType(choice, picked.name) ? `Choose ${choice.typeWords}.` : picked && picked.size === 0 ? "That file is empty." : undefined);
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!file) return setProblem("Choose a file first.");
    if (problem) return;
    start.mutate({ section, file });
  };

  const upload = current.data;
  const busy = start.isPending || Boolean(uploadId && !settled(upload) && !current.error);

  // Only a real server state is shown: nothing while the list loads, and no claim if it failed.
  // The file just sent may be newer than the list, so it replaces its own row (or leads the list).
  const rows = upload ? [upload, ...(recent.data ?? []).filter((u) => u.id !== upload.id)] : (recent.data ?? []);
  const chip = sectionChip(rows);
  // The newest file shows as a row (mocks v16); the ones before it fold away.
  const latest = rows[0];
  const others = rows.slice(1);
  const aside = chip ? (
    <span className={`chip ${chip.tone}`.trim()}>{chip.label}</span>
  ) : recent.isSuccess ? (
    <span className="chip">Nothing uploaded yet</span>
  ) : recent.isError ? (
    <span className="chip">We couldn't load this</span>
  ) : null;

  return (
    <Panel title={label} aside={aside}>
      <p className="pad-x hint">{hint}</p>
      {latest && <Result upload={latest} />}
      {latest && <HeldLink businessId={businessId} upload={latest} />}
      {uploadId && current.error && (
        <Banner tone="error">
          {errorText(current.error)} <Button type="button" variant="link" onClick={() => current.refetch()}>Try again</Button>
        </Banner>
      )}

      {canUpload ? (
        <form onSubmit={submit} noValidate className="drop">
          <div className="field">
            <label htmlFor={`${id}-file`}>{latest ? "Add another file" : "Choose a file"}</label>
            <input
              ref={input}
              id={`${id}-file`}
              type="file"
              accept={acceptFor(choice)}
              aria-invalid={problem ? true : undefined}
              aria-describedby={problem ? `${id}-problem` : undefined}
              onChange={(e) => choose(e.target.files?.[0])}
            />
            {problem && (
              <p id={`${id}-problem`} className="error">
                {problem}
              </p>
            )}
          </div>
          <Button type="submit" variant="secondary" className="btn-sm" busy={busy}>
            {start.isPending ? "Sending…" : busy ? "Reading…" : "Upload"}
          </Button>
          {start.error && <Banner tone="error">{start.error.message || errorText(start.error)}</Banner>}
        </form>
      ) : (
        <p className="pad hint">Only an owner or admin can upload files.</p>
      )}

      {others.length > 0 && (
        <details className="earlier">
          <summary>Earlier files ({others.length})</summary>
          <ul className="list">
            {others.map((u) => (
              <li key={u.id}>
                {u.file_name} · {formatDateTimeIst(u.created_at)}
                <br />
                <span className="hint">{statusText(u)}</span>
                <HeldLink businessId={businessId} upload={u} />
              </li>
            ))}
          </ul>
        </details>
      )}
    </Panel>
  );
}

function Result({ upload }: { upload: Upload }) {
  const failed = upload.status === "rejected";
  const text = statusText(upload);
  return (
    <div role={failed ? "alert" : "status"} className={failed ? "kv bad" : "kv"} aria-busy={!settled(upload) || undefined}>
      <span>{upload.file_name}</span>
      <span>{text}</span>
    </div>
  );
}
