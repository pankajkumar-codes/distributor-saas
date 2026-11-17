import { useEffect, useId, useReducer, useRef, useState, type FormEvent } from "react";

import { errorText, type ApiError } from "../../api/errors";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { ErrorDetail } from "../../kit/ErrorDetail";
import { GIVE_UP_MS, pollingGaveUp, sendBundle, shownName, useBundle, useChooseFile, useStageBundle, type Bundle, type BundleFile } from "./useBundle";

type Props = { businessId: string; bundleId: string | null; onBundle: (id: string | null) => void };

const SECTION_WORDS: Record<NonNullable<BundleFile["section"]>, string> = {
  amazon: "Amazon",
  flipkart: "Flipkart",
  meesho: "Meesho",
  own_invoices_excel: "Your invoices (Excel)",
  own_invoices_pdf: "Your invoices (PDF)",
};
const PDF_NOTE = "Will be read as your invoices. Any we can't read clearly are held for you to look at.";

function sizeWords(bytes: number): string {
  if (bytes < 1024) return `${bytes} bytes`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * One zip of mixed reports. The server sorts the files by what is inside them; the seller sees the list
 * before anything is read, can move a file to another report or leave it out, then asks for the files to be
 * read. Reading goes through the ordinary uploads, so every result shows in the cards below. Which zip the
 * card follows lives in the URL (`?bundle=<id>`), so a reload picks up where it was.
 */
export function BundleCard({ businessId, bundleId, onBundle }: Props) {
  const id = useId();
  const [staging, setStaging] = useState(false);
  const bundle = useBundle(businessId, bundleId, staging);
  const data = bundle.data;

  return (
    <section className="card" aria-labelledby={`${id}-h`}>
      <h2 id={`${id}-h`}>A zip of your reports</h2>
      <p className="hint">
        Put your Amazon, Flipkart and Meesho files and your own sales invoices in one zip. We sort them by what is inside, show you the list, and read
        them only after you say so.
      </p>
      {!bundleId && <StartForm businessId={businessId} onBundle={onBundle} />}
      {bundleId && bundle.isPending && <p aria-busy="true">Loading…</p>}
      {bundleId && bundle.error && (
        <Banner tone="error">
          We couldn't load this zip. {errorText(bundle.error)}
          <ErrorDetail error={bundle.error} />{" "}
          <Button type="button" variant="link" onClick={() => bundle.refetch()}>
            Try again
          </Button>{" "}
          <Button type="button" variant="link" onClick={() => onBundle(null)}>
            Start again
          </Button>
        </Banner>
      )}
      {data && (
        <BundleView
          businessId={businessId}
          bundle={data}
          staging={staging}
          onStaging={setStaging}
          onAgain={() => {
            setStaging(false);
            onBundle(null);
          }}
        />
      )}
    </section>
  );
}

function StartForm({ businessId, onBundle }: { businessId: string; onBundle: (id: string) => void }) {
  const id = useId();
  const key = useRef(crypto.randomUUID());
  const [file, setFile] = useState<File | null>(null);
  const [problem, setProblem] = useState<string>();
  const [error, setError] = useState<ApiError>();
  const [sending, setSending] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(undefined);
    if (!file) return setProblem("Choose a zip file first.");
    if (problem) return;
    setSending(true);
    try {
      onBundle(await sendBundle(businessId, file, key));
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setSending(false);
    }
  };

  return (
    <form onSubmit={submit} noValidate>
      <div className="field">
        <label htmlFor={`${id}-file`}>Choose a zip file</label>
        <input
          id={`${id}-file`}
          type="file"
          accept=".zip"
          aria-invalid={problem ? true : undefined}
          aria-describedby={problem ? `${id}-problem` : undefined}
          onChange={(e) => {
            const picked = e.target.files?.[0] ?? null;
            key.current = crypto.randomUUID();
            setFile(picked);
            setError(undefined);
            setProblem(!picked ? undefined : !picked.name.toLowerCase().endsWith(".zip") ? "That isn't a zip file." : picked.size === 0 ? "That file is empty." : undefined);
          }}
        />
        {problem && (
          <p id={`${id}-problem`} className="error">
            {problem}
          </p>
        )}
      </div>
      {error && (
        <Banner tone="error">
          {errorText(error)}
          <ErrorDetail error={error} />
        </Banner>
      )}
      <Button type="submit" busy={sending}>
        {sending ? "Sending…" : "Send the zip"}
      </Button>
    </form>
  );
}

function BundleView({
  businessId,
  bundle,
  staging,
  onStaging,
  onAgain,
}: {
  businessId: string;
  bundle: Bundle;
  staging: boolean;
  onStaging: (on: boolean) => void;
  onAgain: () => void;
}) {
  const choose = useChooseFile(businessId, bundle.id);
  const stage = useStageBundle(businessId, bundle.id);
  const [moved, setMoved] = useState<{ n: number; message: string }>();

  const [, redraw] = useReducer((n: number) => n + 1, 0);
  const stopped = pollingGaveUp(bundle, staging);
  const watching = !stopped && (bundle.status === "pending" || bundle.status === "received" || bundle.status === "staging" || (staging && bundle.status === "classified"));
  // Polling stops at the limit without anything changing on the screen, so draw once more when it is reached.
  useEffect(() => {
    if (!watching) return;
    const left = Date.parse(bundle.created_at) + GIVE_UP_MS - Date.now();
    const t = setTimeout(redraw, Math.max(0, left) + 50);
    return () => clearTimeout(t);
  }, [watching, bundle.created_at]);

  if (bundle.status === "pending" || bundle.status === "received") {
    return (
      <p aria-busy="true" role="status">
        {stopped ? "This is taking longer than usual. It is still going on our side. Reload this page in a few minutes to check." : "Sorting your files. You can leave this page; it keeps going."}
      </p>
    );
  }
  if (bundle.status === "rejected" || bundle.status === "expired") {
    return (
      <>
        <Banner tone="error">{bundle.status === "expired" ? "This zip has expired. Send it again." : bundle.reject_message || "We couldn't use this zip."}</Banner>
        <Button type="button" onClick={onAgain}>
          Send another zip
        </Button>
      </>
    );
  }

  const readable = bundle.files.filter((f) => f.state === "used");
  const working = bundle.status === "staging" || (staging && bundle.status === "classified");

  if (bundle.status === "staged") {
    return (
      <>
        <p role="status">
          Sent for reading: {readable.length} {readable.length === 1 ? "file" : "files"} from {shownName(bundle.file_name)}. Each result shows in its own card below.
        </p>
        <FileList bundle={bundle} locked choose={undefined} />
        <Button type="button" onClick={onAgain}>
          Send another zip
        </Button>
      </>
    );
  }

  return (
    <>
      <p>
        <strong>{shownName(bundle.file_name)}</strong> · {sizeWords(bundle.size_bytes)}. Check the list, then ask us to read the files.
      </p>
      <FileList
        bundle={bundle}
        locked={working}
        choose={(n, section) => {
          setMoved(undefined);
          choose.mutate(
            { n, section },
            { onError: (e) => setMoved({ n, message: e.message || errorText(e) }) },
          );
        }}
        problem={moved}
      />
      {stage.error && (
        <Banner tone="error">
          {errorText(stage.error)}
          <ErrorDetail error={stage.error} />
        </Banner>
      )}
      {working && stopped && (
        <p role="status" className="hint">
          This is taking longer than usual. It is still going on our side. Reload this page in a few minutes to check.
        </p>
      )}
      {readable.length === 0 && <p className="hint">None of these files can be read. Move one to a report, or send another zip.</p>}
      <Button
        type="button"
        busy={working || stage.isPending}
        disabled={readable.length === 0}
        onClick={() => {
          onStaging(true);
          stage.mutate(undefined, { onError: () => onStaging(false) });
        }}
      >
        {working || stage.isPending ? "Sending them to be read…" : `Read ${readable.length} ${readable.length === 1 ? "file" : "files"}`}
      </Button>{" "}
      <Button type="button" variant="link" onClick={onAgain} disabled={working}>
        Send a different zip
      </Button>
    </>
  );
}

function FileList({
  bundle,
  locked,
  choose,
  problem,
}: {
  bundle: Bundle;
  locked: boolean;
  choose: ((n: number, section: BundleFile["section"]) => void) | undefined;
  problem?: { n: number; message: string };
}) {
  return (
    <table className="products">
      <thead>
        <tr>
          <th scope="col">File</th>
          <th scope="col">What it is</th>
          <th scope="col">What happens</th>
        </tr>
      </thead>
      <tbody>
        {bundle.files.map((f) => (
          <tr key={f.n}>
            <td data-label="File">
              {shownName(f.file_name)}
              <br />
              <span className="hint">{sizeWords(f.size_bytes)}</span>
            </td>
            <td data-label="What it is">
              {choose && !locked && f.state !== "not_selected" ? (
                <select
                  aria-label={`What ${shownName(f.file_name)} is`}
                  value={f.state === "dropped" ? "" : (f.section ?? "")}
                  onChange={(e) => choose(f.n, (e.target.value || null) as BundleFile["section"])}
                >
                  <option value="">Don't use this file</option>
                  {bundle.selectable_sections.map((s) => (
                    <option key={s} value={s}>
                      {SECTION_WORDS[s]}
                    </option>
                  ))}
                </select>
              ) : (
                (f.section && SECTION_WORDS[f.section]) || "—"
              )}
              {problem?.n === f.n && (
                <p className="error" role="alert">
                  {problem.message}
                </p>
              )}
            </td>
            <td data-label="What happens">
              <FileOutcome file={f} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function FileOutcome({ file }: { file: BundleFile }) {
  if (file.state === "used") {
    const note = file.note ?? (file.section === "own_invoices_pdf" ? PDF_NOTE : null);
    return (
      <>
        Will be read.
        {note && (
          <>
            <br />
            <span className="hint">{note}</span>
          </>
        )}
      </>
    );
  }
  if (file.state === "dropped") return <>Left out. You chose not to use it.</>;
  return <>Not used. {file.reason ?? ""}</>;
}
