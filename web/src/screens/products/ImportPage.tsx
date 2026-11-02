import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type FormEvent } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { uploadTo } from "../../api/upload";
import { pollDelay, useJob } from "../../api/useJob";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { NotFound } from "../../kit/NotFound";
import { TopBar } from "../../kit/TopBar";
import { ImportRows, STATUS_LABEL, type RowStatus } from "./ImportRows";

type Run = components["schemas"]["ImportOut"];
const PAGE = 50;
const BUSY = new Set<Run["status"]>(["parsing", "applying"]);
const TABS: RowStatus[] = ["new", "changed", "unchanged", "invalid", "conflict"];

/**
 * M8 product import (LLD-3 §6.3, §7). Every row's outcome is the server's: the web never
 * checks a row itself. The run ID (and the job being waited on) live in the URL, so a reload
 * resumes at the same step. Start is idempotent per chosen file; confirm per run.
 */
export function ImportPage() {
  const { businessId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const runId = params.get("run");
  const jobId = params.get("job");
  const tab = TABS.find((t) => t === params.get("rows")) ?? null;
  const businesses = useMyBusinesses();
  const business = businesses.data?.find((b) => b.business_id === businessId);
  const queryClient = useQueryClient();
  const path = { business_id: businessId };
  const [file, setFile] = useState<File | null>(null);
  const startKey = useRef(crypto.randomUUID()); // one per chosen file
  const [applyChanges, setApplyChanges] = useState(true);
  const [confirmError, setConfirmError] = useState<string | null>(null);

  const go = (next: Record<string, string | null>) =>
    setParams((prev) => {
      const out = new URLSearchParams(prev);
      for (const [k, v] of Object.entries(next)) {
        if (v) out.set(k, v);
        else out.delete(k);
      }
      return out;
    });

  const job = useJob(businessId, jobId);
  const run = useInfiniteQuery<Run, ApiError>({
    queryKey: ["b", businessId, "import", runId, tab],
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      call(() =>
        api.GET("/api/v1/b/{business_id}/product-imports/{import_id}", {
          params: { path: { ...path, import_id: runId ?? "" }, query: { rows: tab ?? undefined, limit: PAGE, offset: pageParam as number } },
        }),
      ),
    getNextPageParam: (last, pages) => (last.has_more ? pages.length * PAGE : undefined),
    enabled: Boolean(business && runId),
    // While the server works, look again with the job poll's gaps; a job that failed stops it.
    refetchInterval: (q) => {
      const status = q.state.data?.pages[0]?.status;
      return status && BUSY.has(status) && job.data?.status !== "failed" ? pollDelay(q.state.dataUpdateCount) : false;
    },
  });

  const start = useMutation<void, ApiError>({
    mutationFn: async () => {
      const f = file!;
      const started = await call(() =>
        api.POST("/api/v1/b/{business_id}/product-imports", {
          params: { path, header: { "Idempotency-Key": startKey.current } },
          body: { file_name: f.name, size_bytes: f.size },
        }),
      );
      await uploadTo(started.upload, f);
      const done = await call(() =>
        api.POST("/api/v1/b/{business_id}/product-imports/{import_id}/complete", { params: { path: { ...path, import_id: started.import_id } } }),
      );
      go({ run: started.import_id, job: done.job_id, rows: null });
    },
  });

  const confirm = useMutation<{ job_id: string }, ApiError, boolean>({
    mutationFn: (apply) =>
      call(() =>
        api.POST("/api/v1/b/{business_id}/product-imports/{import_id}/confirm", {
          params: { path: { ...path, import_id: runId! } },
          body: { apply_changes: apply },
        }),
      ),
    onMutate: () => setConfirmError(null),
    onSuccess: (r) => {
      go({ job: r.job_id, rows: null });
      queryClient.invalidateQueries({ queryKey: ["b", businessId, "import", runId] });
    },
    onError: async (e, apply) => {
      if (e.code !== "import_already_applied") return;
      // Success only if the server shows this very run applied with this choice; anything
      // else (another choice, another run) is the server's message, not a quiet success.
      const fresh = await run.refetch();
      const now = fresh.data?.pages[0];
      if (!(now?.status === "applied" && now.apply_changes === apply)) setConfirmError(e.message || errorText(e));
    },
  });

  const discard = useMutation<unknown, ApiError>({
    mutationFn: () =>
      call(() => api.POST("/api/v1/b/{business_id}/product-imports/{import_id}/discard", { params: { path: { ...path, import_id: runId! } } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["b", businessId, "import", runId] }),
  });

  const template = useMutation<void, ApiError>({
    mutationFn: async () => {
      const text = await call(() => api.GET("/api/v1/b/{business_id}/products/import-template", { params: { path }, parseAs: "text" }));
      const url = URL.createObjectURL(new Blob([text as string], { type: "text/csv" }));
      const a = Object.assign(document.createElement("a"), { href: url, download: "products-template.csv" });
      a.click();
      URL.revokeObjectURL(url);
    },
  });

  if (businesses.isPending) {
    return (
      <main className="page" aria-busy="true">
        <p>Loading…</p>
      </main>
    );
  }
  if (!business || run.error?.status === 404) return <NotFound />;

  const current = run.data?.pages[0];
  const rows = run.data?.pages.flatMap((p) => p.rows) ?? [];
  const counts = current?.counts ?? {};
  const n = (k: string) => counts[k] ?? 0;
  const willApply = n("new") + (applyChanges ? n("changed") : 0);
  const startOver = () => {
    startKey.current = crypto.randomUUID();
    setFile(null);
    start.reset();
    confirm.reset();
    setConfirmError(null);
    go({ run: null, job: null, rows: null });
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (file) start.mutate();
  };
  const table = (
    <>
      <ImportRows rows={rows} />
      {run.hasNextPage && (
        <Button type="button" busy={run.isFetchingNextPage} onClick={() => run.fetchNextPage()}>
          Load more
        </Button>
      )}
    </>
  );

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page page-wide">
        <p className="step">
          <Link to={`/b/${businessId}/products`}>Products</Link>
        </p>
        <h1>Import products from a file</h1>
        {run.error && <Banner tone="error">{errorText(run.error)}</Banner>}
        {job.data?.status === "failed" && current && BUSY.has(current.status) && (
          <Banner tone="error">
            The import stopped before it finished ({job.data.error_code ?? "error"}). Nothing was saved.{" "}
            <Button type="button" variant="link" onClick={startOver}>
              Start a new import
            </Button>
          </Banner>
        )}

        {(confirm.error && confirm.error.code !== "import_already_applied") || confirmError ? (
          <Banner tone="error">{confirmError ?? (confirm.error!.message || errorText(confirm.error!))}</Banner>
        ) : null}

        {!runId && (
          <form onSubmit={submit} noValidate>
            <p>
              Use a CSV file, or the first sheet of an Excel file, with this header row:{" "}
              <code>code, name, hsn, unit, sale_rate, gst_rate, gst_rate_valid_from, barcode, tax_category, has_cess</code>
            </p>
            <p>
              <Button type="button" variant="link" busy={template.isPending} onClick={() => template.mutate()}>
                Download the template
              </Button>
            </p>
            <div className="field">
              <label htmlFor="import-file">File</label>
              <input
                id="import-file"
                type="file"
                accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                onChange={(e) => {
                  startKey.current = crypto.randomUUID();
                  start.reset();
                  setFile(e.target.files?.[0] ?? null);
                }}
              />
            </div>
            {start.error && (
              <Banner tone="error">
                {start.error.status === 0
                  ? "The file didn't reach us. Check your connection and try again."
                  : start.error.status === 403
                    ? "The upload was refused. Choose the file again."
                    : (start.error.fix ?? (start.error.message || errorText(start.error)))}
              </Banner>
            )}
            <div className="actions">
              <Button type="submit" busy={start.isPending} disabled={!file}>
                Upload and check
              </Button>
            </div>
          </form>
        )}

        {current?.status === "awaiting_upload" && (
          <Banner tone="error">
            The file didn't finish uploading.{" "}
            <Button type="button" variant="link" onClick={startOver}>
              Choose it again
            </Button>
          </Banner>
        )}
        {current && BUSY.has(current.status) && (
          <p aria-busy="true" role="status">
            {current.status === "parsing" ? "Checking your file…" : "Importing…"}
            {job.data?.progress?.out_of ? ` ${job.data.progress.done} of ${job.data.progress.out_of} rows.` : ""}
          </p>
        )}

        {current?.status === "preview" && (
          <>
            <p role="status">
              {current.file_name}: {n("new")} new, {n("changed")} changed, {n("unchanged")} unchanged, {n("invalid")} with errors,{" "}
              {n("conflict")} with a repeated code.
            </p>
            {(n("invalid") > 0 || n("conflict") > 0) && (
              <Banner>Rows with errors or a repeated code are never imported. Fix them in the file and upload it again.</Banner>
            )}
            <div className="tabs" role="group" aria-label="Show rows">
              <button type="button" className="tab" aria-pressed={tab === null} onClick={() => go({ rows: null })}>
                All
              </button>
              {TABS.map((t) => (
                <button key={t} type="button" className="tab" aria-pressed={tab === t} onClick={() => go({ rows: t })}>
                  {STATUS_LABEL[t]} ({n(t)})
                </button>
              ))}
            </div>
            {table}
            {n("changed") > 0 && (
              <label className="radio">
                <input type="checkbox" checked={applyChanges} onChange={(e) => setApplyChanges(e.target.checked)} />
                Also apply the {n("changed")} changes to existing products
              </label>
            )}
            {discard.error && <Banner tone="error">{discard.error.message || errorText(discard.error)}</Banner>}
            <div className="actions">
              <Button type="button" busy={confirm.isPending} disabled={willApply === 0 || confirm.isSuccess} onClick={() => confirm.mutate(applyChanges)}>
                {willApply === 0 ? "Nothing to import" : `Import ${willApply} product${willApply === 1 ? "" : "s"}`}
              </Button>{" "}
              <Button type="button" variant="link" busy={discard.isPending} onClick={() => discard.mutate()}>
                Discard
              </Button>
            </div>
          </>
        )}

        {current?.status === "applied" && (
          <>
            <Banner>
              Imported: {n("applied")} applied, {n("skipped")} skipped, {n("stale")} not applied because the product changed after
              the preview. New GST rates are marked not confirmed until you confirm them with your CA.
            </Banner>
            {n("stale") > 0 && <p>To bring in the rows that weren't applied, upload the file again for a fresh preview.</p>}
            {table}
            <p>
              <Link to={`/b/${businessId}/products`}>Go to products</Link>{" "}
              <Button type="button" variant="link" onClick={startOver}>
                Import another file
              </Button>
            </p>
          </>
        )}

        {(current?.status === "discarded" || current?.status === "failed") && (
          <Banner tone={current.status === "failed" ? "error" : undefined}>
            {current.superseded_by ? (
              <>
                A newer upload of this file replaced this preview.{" "}
                <Link to={`?run=${current.superseded_by}`}>Open the newer preview</Link>.
              </>
            ) : (
              (current.error_message ?? "Nothing was saved.")
            )}{" "}
            <Button type="button" variant="link" onClick={startOver}>
              Start a new import
            </Button>
          </Banner>
        )}
      </main>
    </>
  );
}
