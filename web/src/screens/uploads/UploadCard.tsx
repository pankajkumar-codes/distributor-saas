import { useId, useRef, useState, type FormEvent } from "react";

import { errorText } from "../../api/errors";
import { formatDateTimeIst } from "../../format/dates";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { ACCEPT, settled, statusText, wrongType, type Section, type Upload } from "./sections";
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
    setProblem(picked && wrongType(picked.name) ? "Choose a CSV, Excel or zip file." : picked && picked.size === 0 ? "That file is empty." : undefined);
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!file) return setProblem("Choose a file first.");
    if (problem) return;
    start.mutate({ section, file });
  };

  const upload = current.data;
  const busy = start.isPending || Boolean(uploadId && !settled(upload) && !current.error);
  const others = (recent.data ?? []).filter((u) => u.id !== uploadId);

  return (
    <section className="card" aria-labelledby={`${id}-h`}>
      <h2 id={`${id}-h`}>{label}</h2>
      <p className="hint">{hint}</p>

      {upload && <Result upload={upload} />}
      {uploadId && current.error && (
        <Banner tone="error">
          {errorText(current.error)} <Button type="button" variant="link" onClick={() => current.refetch()}>Try again</Button>
        </Banner>
      )}

      {canUpload ? (
        <form onSubmit={submit} noValidate>
          <div className="field">
            <label htmlFor={`${id}-file`}>{upload ? "Add another file" : "Choose a file"}</label>
            <input
              ref={input}
              id={`${id}-file`}
              type="file"
              accept={ACCEPT}
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
          {start.error && <Banner tone="error">{start.error.message || errorText(start.error)}</Banner>}
          <Button type="submit" busy={busy}>
            {start.isPending ? "Sending…" : busy ? "Reading…" : "Upload"}
          </Button>
        </form>
      ) : (
        <p className="hint">Only an owner or admin can upload files.</p>
      )}

      {others.length > 0 && (
        <>
          <h3>Earlier files</h3>
          <ul className="list">
            {others.map((u) => (
              <li key={u.id}>
                {u.file_name} · {formatDateTimeIst(u.created_at)}
                <br />
                <span className="hint">{statusText(u)}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function Result({ upload }: { upload: Upload }) {
  const failed = upload.status === "rejected";
  const text = statusText(upload);
  return (
    <div role={failed ? "alert" : "status"} className={failed ? "banner banner-error" : "banner banner-info"} aria-busy={!settled(upload) || undefined}>
      <strong>{upload.file_name}</strong>
      <br />
      {text}
    </div>
  );
}
