import { useQueryClient } from "@tanstack/react-query";
import { useId, useRef, useState, type FormEvent } from "react";

import { errorText, type ApiError } from "../../api/errors";
import { formatDateTimeIst } from "../../format/dates";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { OWN_INVOICE_TYPES, ownInvoiceProblem, ownInvoiceSection, settled, statusText, type Upload } from "./sections";
import { sendFile, uploadsKey, useUploads } from "./useUpload";

type Props = { businessId: string; label: string; hint: string; canUpload: boolean };

/**
 * Your own sales invoices: an Excel sheet, PDF invoices, or both, several files at once. Each file goes
 * to the section its type belongs to (Excel and CSV to the sheet reader, PDF to the PDF reader). The
 * server still decides everything about a file and answers in words; this card only shows them.
 * A zip of PDFs is not offered until the server takes one.
 */
export function OwnInvoicesCard({ businessId, label, hint, canUpload }: Props) {
  const id = useId();
  const queryClient = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const keys = useRef(new Map<File, { current: string }>()); // one idempotency key per chosen file
  const [files, setFiles] = useState<File[]>([]);
  const [problems, setProblems] = useState<string[]>([]);
  const [failed, setFailed] = useState<{ name: string; message: string }[]>([]);
  const [sending, setSending] = useState(false);
  const sheets = useUploads(businessId, "own_invoices_excel", true, true);
  const pdfs = useUploads(businessId, "own_invoices_pdf", true, true);
  const uploads = [...(sheets.data ?? []), ...(pdfs.data ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at));

  const choose = (picked: FileList | null) => {
    const chosen = Array.from(picked ?? []);
    keys.current = new Map(chosen.map((f) => [f, keys.current.get(f) ?? { current: crypto.randomUUID() }]));
    setFiles(chosen);
    setFailed([]);
    setProblems(chosen.flatMap((f) => (ownInvoiceProblem(f) ? [`${f.name}: ${ownInvoiceProblem(f)}`] : [])));
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (files.length === 0) return setProblems(["Choose a file first."]);
    if (problems.length > 0) return;
    setSending(true);
    const left: File[] = [];
    const errors: { name: string; message: string }[] = [];
    for (const file of files) {
      try {
        await sendFile(businessId, ownInvoiceSection(file.name), file, keys.current.get(file) ?? { current: crypto.randomUUID() });
      } catch (err) {
        const e2 = err as ApiError;
        left.push(file);
        errors.push({ name: file.name, message: e2.message || errorText(e2) });
      }
    }
    setSending(false);
    void queryClient.invalidateQueries({ queryKey: uploadsKey(businessId) }); // the list picks up the new files; the form does not wait for it
    setFiles(left); // only the ones that did not get through stay chosen, so pressing Upload again retries just those
    setFailed(errors);
    if (left.length === 0 && input.current) input.current.value = "";
  };

  return (
    <section className="card" aria-labelledby={`${id}-h`}>
      <h2 id={`${id}-h`}>{label}</h2>
      <p className="hint">{hint}</p>

      {uploads.length > 0 && (
        <ul className="list">
          {uploads.map((u) => (
            <li key={u.id}>
              <FileLine upload={u} />
            </li>
          ))}
        </ul>
      )}
      {(sheets.error || pdfs.error) && <Banner tone="error">{errorText((sheets.error ?? pdfs.error)!)}</Banner>}

      {canUpload ? (
        <form onSubmit={submit} noValidate>
          <div className="field">
            <label htmlFor={`${id}-file`}>{uploads.length > 0 ? "Add more files" : "Choose files"}</label>
            <input
              ref={input}
              id={`${id}-file`}
              type="file"
              multiple
              accept={OWN_INVOICE_TYPES.join(",")}
              aria-invalid={problems.length > 0 ? true : undefined}
              aria-describedby={problems.length > 0 ? `${id}-problem` : undefined}
              onChange={(e) => choose(e.target.files)}
            />
            {problems.length > 0 && (
              <div id={`${id}-problem`} className="error">
                <p>Nothing was sent. Fix this and choose the files again:</p>
                {problems.map((p) => (
                  <p key={p}>{p}</p>
                ))}
              </div>
            )}
          </div>
          {failed.length > 0 && (
            <Banner tone="error">
              {failed.map((f) => (
                <p key={f.name}>
                  {f.name}: {f.message}
                </p>
              ))}
              Press Upload to send these again.
            </Banner>
          )}
          <Button type="submit" busy={sending}>
            {sending ? "Sending…" : "Upload"}
          </Button>
        </form>
      ) : (
        <p className="hint">Only an owner or admin can upload files.</p>
      )}
    </section>
  );
}

function FileLine({ upload }: { upload: Upload }) {
  const rejected = upload.status === "rejected";
  return (
    <>
      <strong>{upload.file_name}</strong> · {formatDateTimeIst(upload.created_at)}
      <br />
      <span className={rejected ? "error" : "hint"} role={rejected ? "alert" : undefined} aria-busy={!settled(upload) || undefined}>
        {statusText(upload)}
      </span>
    </>
  );
}
