import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { Field } from "../../kit/Field";

type NumberingOut = components["schemas"]["NumberingOut"];
type SeriesOut = components["schemas"]["SeriesOut"];
type Kind = SeriesOut["kind"];
type Edit = { prefix: string; first: string };

/** "INV" in November 2026 -> "INV/26-11/000001": the number a new series starts with, as the server shows it. */
export function previewNumber(prefix: string, first: number, width: number, scope: string, on: Date): string {
  const digits = String(first).padStart(width, "0");
  if (scope !== "gstin_kind_month") return `${prefix}${digits}`;
  const yy = String(on.getFullYear() % 100).padStart(2, "0");
  const mm = String(on.getMonth() + 1).padStart(2, "0");
  return `${prefix}/${yy}-${mm}/${digits}`;
}

/** What is wrong with a prefix before it is sent, or undefined. The server checks it again. */
export function prefixProblem(prefix: string, maxPrefix: number): string | undefined {
  if (!prefix) return "Enter a prefix, like INV.";
  if (!/^[A-Z0-9]+$/.test(prefix)) return "Use letters and digits only.";
  if (prefix.length > maxPrefix) return `Use at most ${maxPrefix} letters: GST allows 16 characters in a number.`;
  return undefined;
}

const fromSaved = (n: NumberingOut): Record<Kind, Edit> =>
  Object.fromEntries(n.series.map((s) => [s.kind, { prefix: s.prefix, first: String(s.first_number) }])) as Record<Kind, Edit>;

/**
 * Invoice numbering (#461): the prefix of each numbered document type and the invoice series' first number, with the
 * number a new series would start with (D-114: INV/YY-MM/NNNNNN, restarting each month). Live numbering is shown, never
 * switched, here. Anyone who can open Settings can see it; the server decides who can save.
 */
export function NumberingSection({ businessId, canEdit }: { businessId: string; canEdit: boolean }) {
  const queryClient = useQueryClient();
  const key = ["b", businessId, "numbering"];
  const saved = useQuery<NumberingOut, ApiError>({
    queryKey: key,
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/numbering", { params: { path: { business_id: businessId } } })),
  });
  const [edited, setEdited] = useState<Record<Kind, Edit> | null>(null);
  const n = saved.data;
  const shown = edited ?? (n ? fromSaved(n) : null);
  const save = useMutation<NumberingOut, ApiError, Record<Kind, Edit>>({
    mutationFn: (e) =>
      call(() =>
        api.PUT("/api/v1/b/{business_id}/numbering", {
          params: { path: { business_id: businessId } },
          body: Object.fromEntries(
            Object.entries(e).map(([k, v]) => [k, { prefix: v.prefix, first_number: Number(v.first) || 1 }]),
          ) as components["schemas"]["NumberingIn"],
        }),
      ),
    onSuccess: (out) => {
      queryClient.setQueryData(key, out);
      setEdited(null);
    },
  });

  const problems: Partial<Record<Kind, string>> = {};
  if (n && shown) {
    for (const s of n.series) {
      const p = prefixProblem(shown[s.kind].prefix, n.max_prefix_length);
      if (p) problems[s.kind] = p;
      else if (n.series.some((o) => o.kind !== s.kind && shown[o.kind].prefix === shown[s.kind].prefix)) problems[s.kind] = "Each document type needs its own prefix.";
    }
  }
  const firstProblem = shown && !/^[1-9][0-9]{0,5}$/.test(shown.invoice.first) ? "Enter a number from 1 to 999999." : undefined;
  const dirty = Boolean(n && shown && JSON.stringify(shown) !== JSON.stringify(fromSaved(n)));
  const ok = Object.keys(problems).length === 0 && !firstProblem;
  const change = (kind: Kind, part: keyof Edit, value: string) => {
    if (!shown) return;
    if (save.isSuccess || save.isError) save.reset();
    setEdited({ ...shown, [kind]: { ...shown[kind], [part]: part === "prefix" ? value.toUpperCase().trim() : value.trim() } });
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (shown && dirty && ok) save.mutate(shown);
  };
  const today = new Date();

  return (
    <section className="panel" aria-labelledby="numbering">
      <div className="panel-h">
        <h2 id="numbering">Your series</h2>
      </div>
      <div className="pad">
        {saved.isPending && <p className="hint">Loading…</p>}
        {saved.isError && <Banner tone="error">We couldn't load this. {errorText(saved.error)}</Banner>}
        {n && shown && (
          <form onSubmit={submit} noValidate>
            <p className="hint">
              {n.live
                ? "Live numbering is on."
                : n.live_available
                  ? "Live numbering is off: every invoice is a practice one until you turn it on."
                  : "Live numbering is off: every invoice is a practice one for now."}{" "}
              Each number is the prefix, the month of the document's date and a 6-digit count that starts again each month.
            </p>
            {n.series.map((s) => {
              const e = shown[s.kind];
              const first = s.kind === "invoice" ? Number(e.first) || 1 : s.first_number;
              return (
                <fieldset key={s.kind} className="plain numbering-row">
                  <legend>{s.label}</legend>
                  <Field
                    label={`${s.label} prefix`}
                    value={e.prefix}
                    maxLength={n.max_prefix_length + 2}
                    autoCapitalize="characters"
                    disabled={!canEdit}
                    onChange={(ev) => change(s.kind, "prefix", ev.target.value)}
                    error={problems[s.kind]}
                    hint={
                      problems[s.kind]
                        ? undefined
                        : `Next new series starts at ${previewNumber(e.prefix, first, s.width, n.scope, today)}` +
                          (s.issued_in_app ? "" : ". Debit notes aren't made in Kartaa yet: issue them in your own series and add it to Table 13.")
                    }
                  />
                  {s.kind === "invoice" && (
                    <Field
                      label="First invoice number this financial year"
                      inputMode="numeric"
                      value={e.first}
                      disabled={!canEdit}
                      onChange={(ev) => change(s.kind, "first", ev.target.value)}
                      error={firstProblem}
                      hint={firstProblem ? undefined : "Only if you already issued invoices this year in other software and are continuing that count."}
                    />
                  )}
                </fieldset>
              );
            })}
            <p className="hint">A series already started keeps its prefix; a change applies from the next new series.</p>
            {save.isError && <Banner tone="error">{errorText(save.error)}</Banner>}
            {save.isSuccess && <Banner>Saved.</Banner>}
            {canEdit && (
              <div className="actions">
                <Button type="submit" busy={save.isPending} disabled={!dirty || !ok}>
                  Save numbering
                </Button>
              </div>
            )}
          </form>
        )}
      </div>
    </section>
  );
}
