import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { useStateCodes } from "../../api/useStateCodes";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { fyIst, previousFy } from "../../format/dates";
import { AddressFields, addressIn, addressLine, addressOf, sameAddress, type Address } from "../../kit/AddressFields";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { Field } from "../../kit/Field";
import { NotFound } from "../../kit/NotFound";
import { RadioGroup } from "../../kit/RadioGroup";
import { TopBar } from "../../kit/TopBar";
import { BAND_OPTIONS } from "../onboarding/BusinessPage";
import { warningText } from "../onboarding/warnings";

type Profile = components["schemas"]["ProfileOut"];
type Updated = { profile: Profile; warnings: string[] };
type Band = components["schemas"]["TurnoverBandIn"]["band"];
type BandOut = components["schemas"]["TurnoverBandOut"];
type Einvoice = "no" | "yes" | "not_sure";
export type Values = {
  legal_name: string;
  trade_name: string;
  address: Address;
  einvoice_history: Einvoice | "";
  this_band: Band | "";
  last_band: Band | "";
};
type Key = keyof Values;
// The two bands are saved with their own route and version (PUT /turnover-bands/{fy}), not PATCH.
const BAND_KEYS: Key[] = ["this_band", "last_band"];

const EDITORS = new Set(["owner", "admin"]); // settings.edit; the server refuses the rest anyway
const MISSING: Record<string, string> = { legal_name: "legal name", address: "address", gstin: "GSTIN" };
const EINVOICE: { value: Einvoice; label: string }[] = [
  { value: "yes", label: "Yes" },
  { value: "no", label: "No" },
  { value: "not_sure", label: "Not sure" },
];

export const valuesOf = (p: Profile): Values => ({
  legal_name: p.legal_name ?? "",
  trade_name: p.trade_name ?? "",
  address: addressOf(p.address),
  einvoice_history: p.einvoice_history ?? "",
  this_band: p.turnover_band?.band ?? "",
  last_band: p.previous_turnover_band?.band ?? "",
});
/** What changes when anyone saves: the profile's version or either band's. */
const stamp = (p: Profile) => `${p.version}/${p.turnover_band?.version ?? 0}/${p.previous_turnover_band?.version ?? 0}`;
const equal = (a: Values[Key], b: Values[Key]) =>
  typeof a === "object" && typeof b === "object" ? sameAddress(a, b) : String(a).trim() === String(b).trim();

/** The fields that differ from `from`. */
export function changedKeys(from: Values, to: Values): Key[] {
  return (Object.keys(to) as Key[]).filter((k) => !equal(from[k], to[k]));
}

/** PATCH sends only the changed fields; an address goes whole. */
export function patchBody(from: Values, to: Values): components["schemas"]["ProfilePatch"] {
  const out: components["schemas"]["ProfilePatch"] = {};
  for (const k of changedKeys(from, to)) {
    if (k === "this_band" || k === "last_band") continue;
    if (k === "address") out.address = addressIn(to.address);
    else if (k === "einvoice_history") out.einvoice_history = to.einvoice_history || null;
    else out[k] = to[k].trim() || null;
  }
  return out;
}

/** The newer saved values with the user's own edits (against `opened`) laid over them. */
export function rebase(opened: Values, latest: Values, values: Values): Values {
  const out = { ...latest };
  for (const k of changedKeys(opened, values)) (out as Record<Key, unknown>)[k] = values[k];
  return out;
}

/**
 * Business details (LLD-1 §8.2) at /settings/company. The server checks every value and
 * returns warnings (a state that doesn't match the GSTIN, say) in codes the web words.
 * Edits follow the product and customer forms: If-Match is the version the edits are
 * against, and it moves only with a save or with the "someone changed this" banner.
 */
export function CompanyPage() {
  const { businessId = "" } = useParams();
  const queryClient = useQueryClient();
  const businesses = useMyBusinesses();
  const business = businesses.data?.find((b) => b.business_id === businessId);
  const states = useStateCodes();
  const path = { business_id: businessId };

  const profile = useQuery<Profile, ApiError>({
    queryKey: ["b", businessId, "profile"],
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/profile", { params: { path } })),
    enabled: Boolean(business),
  });
  const [values, setValues] = useState<Values | null>(null);
  const [opened, setOpened] = useState<Profile | null>(null);
  const [theirs, setTheirs] = useState<Key[]>([]);
  const [stale, setStale] = useState(false);
  const [warnings, setWarnings] = useState<string[]>([]);
  const latest = profile.data ?? null;
  const wrote = useRef(false); // a save that failed after some of its writes landed
  const quiet = useRef(false); // the next newer version is our own partial save, not someone else's

  useEffect(() => {
    if (!latest || (opened && stamp(latest) === stamp(opened))) return;
    if (!opened || !values) {
      setValues(valuesOf(latest));
    } else {
      setValues(rebase(valuesOf(opened), valuesOf(latest), values));
      if (!quiet.current) {
        setTheirs(changedKeys(valuesOf(opened), valuesOf(latest)));
        setStale(true);
      }
    }
    quiet.current = false;
    setOpened(latest);
  }, [latest]); // opened and values are read to rebase onto a newer version, not to trigger it

  const thisFy = opened?.turnover_band?.fy ?? fyIst();
  const lastFy = opened?.previous_turnover_band?.fy ?? previousFy(thisFy);
  const putBand = (fy: string, saved: BandOut | null | undefined, band: Band) =>
    call(() =>
      api.PUT("/api/v1/b/{business_id}/turnover-bands/{fy}", {
        // The first band for a year takes no If-Match; changing one takes the version shown.
        params: { path: { ...path, fy }, header: saved ? { "If-Match": String(saved.version) } : {} },
        body: { band, declared_turnover: saved?.declared_turnover ?? null },
      }),
    );

  const save = useMutation<Updated, ApiError>({
    mutationFn: async () => {
      const from = valuesOf(opened!);
      const keys = changedKeys(from, values!);
      let now: Profile = opened!;
      let out: string[] = [];
      if (keys.some((k) => !BAND_KEYS.includes(k))) {
        const patched = await call(() =>
          api.PATCH("/api/v1/b/{business_id}/profile", {
            params: { path, header: { "If-Match": String(opened!.version) } },
            body: patchBody(from, values!),
          }),
        );
        ({ profile: now, warnings: out } = patched);
        wrote.current = true;
      }
      // Each reply is the saved row, so the form ends on what the server holds without a re-read.
      if (keys.includes("this_band") && values!.this_band) {
        now = { ...now, turnover_band: await putBand(thisFy, opened!.turnover_band, values!.this_band) };
        wrote.current = true;
      }
      if (keys.includes("last_band") && values!.last_band) {
        now = { ...now, previous_turnover_band: await putBand(lastFy, opened!.previous_turnover_band, values!.last_band) };
        wrote.current = true;
      }
      return { profile: now, warnings: out };
    },
    onMutate: () => {
      setWarnings([]);
      wrote.current = false;
    },
    onSuccess: (out) => {
      queryClient.setQueryData(["b", businessId, "profile"], out.profile);
      queryClient.invalidateQueries({ queryKey: ["b", businessId, "home"] });
      queryClient.invalidateQueries({ queryKey: ["me", "businesses"] }); // the top bar shows the trade name
      setOpened(out.profile);
      setValues(valuesOf(out.profile));
      setStale(false);
      setTheirs([]);
      setWarnings(out.warnings);
    },
    onError: (e) => {
      // Someone else saved first: the newer version brings the banner. A band that someone
      // set meanwhile answers if_match_required, which is the same thing.
      if (e.code === "stale_record" || e.code === "if_match_required") profile.refetch();
      else if (wrote.current) {
        quiet.current = true; // our own writes moved the versions; keep the rest of the edits
        profile.refetch();
      }
    },
  });

  if (businesses.isPending || (business && profile.isPending)) {
    return (
      <main className="page" aria-busy="true">
        <p>Loading…</p>
      </main>
    );
  }
  if (businesses.error) {
    return (
      <main className="page">
        <Banner tone="error">{errorText(businesses.error)}</Banner>
      </main>
    );
  }
  if (!business || profile.error?.status === 404) return <NotFound />;
  if (!opened || !values) {
    // A failed load is not an empty form: saving one would have nothing to edit against.
    return (
      <>
        <TopBar title={business.display_name} gstin={business.gstin} />
        <main className="page">
          <Banner tone="error">
            We couldn't load your business details. {profile.error ? errorText(profile.error) : ""}{" "}
            <Button type="button" variant="link" onClick={() => profile.refetch()}>
              Try again
            </Button>
          </Banner>
        </main>
      </>
    );
  }

  const canEdit = EDITORS.has(business.role);
  const error = save.error && !["stale_record", "if_match_required"].includes(save.error.code ?? "") ? save.error : null;
  const words = (e: ApiError) => e.fix ?? (e.message || errorText(e));
  const errorFor = (field: string) => (error && error.field === field ? words(error) : undefined);
  const onField = error && /^(legal_name|trade_name|einvoice_history|address(\..+)?)$/.test(error.field ?? "");
  const theirHint = (k: Key) => {
    if (!stale || !theirs.includes(k)) return undefined;
    const now = valuesOf(opened)[k];
    if (equal(now, values[k])) return "Someone else changed this.";
    if (typeof now === "object") return `Now saved as: ${addressLine(now)}`;
    const label = [...EINVOICE, ...BAND_OPTIONS].find((o) => o.value === now)?.label;
    return `Now saved as: ${label ?? (now || "(blank)")}`;
  };
  // A new edit clears the last save's banner or error (it no longer describes the form).
  const edit = (next: Values) => {
    if (save.isSuccess || save.isError) save.reset();
    setValues(next);
  };
  const dirty = changedKeys(valuesOf(opened), values).length > 0;
  const reg = opened.registration;
  const stateOptions = (states.data ?? []).map((s) => ({ value: s.code, label: `${s.name} (${s.code})` }));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (dirty) save.mutate();
  };

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page">
        <p className="step">
          <Link to={`/b/${businessId}/home`}>Home</Link>
        </p>
        <h1>Business details</h1>
        {!opened.ready_for_documents.ok && opened.ready_for_documents.missing.length > 0 && (
          <Banner>
            Needed before your first invoice: {opened.ready_for_documents.missing.map((m) => MISSING[m] ?? m).join(", ")}.
            {/* The registration is read-only here until the GSTIN change is built (follow-up). */}
            {opened.ready_for_documents.missing.includes("gstin") && " Adding a GSTIN isn't available in the app yet."}
          </Banner>
        )}
        {stale && (
          <Banner tone="error">
            Someone changed these details since you opened them. Your changes are still here; check them against what's saved
            now, then save again.
          </Banner>
        )}
        {error && !onField && <Banner tone="error">{words(error)}</Banner>}
        {states.isError && <Banner tone="error">We couldn't load the list of states. {errorText(states.error)}</Banner>}
        {save.isSuccess && (
          <Banner>
            Saved. Invoices already finalized keep the details they were issued with.
            {warnings.length > 0 && (
              <ul>
                {warnings.map((w) => (
                  <li key={w}>{warningText(w)}</li>
                ))}
              </ul>
            )}
          </Banner>
        )}

        <section className="card" aria-labelledby="registration">
          <h2 id="registration">GST registration</h2>
          <p>
            {reg.kind === "gstin" ? `GSTIN ${reg.gstin ?? "—"}` : `Enrolment number ${reg.enrolment_number ?? "—"}`}
            {reg.state_name ? `, ${reg.state_name}` : ""}
          </p>
          {reg.locked && <p className="hint">This can't change now that invoices have been issued under it.</p>}
        </section>

        <form onSubmit={submit} noValidate>
          <fieldset disabled={!canEdit} className="plain">
            <Field
              label="Legal name"
              value={values.legal_name}
              onChange={(e) => edit({ ...values, legal_name: e.target.value })}
              hint={theirHint("legal_name") ?? "As on your GST registration."}
              error={errorFor("legal_name")}
            />
            <Field
              label="Trade name (optional)"
              value={values.trade_name}
              onChange={(e) => edit({ ...values, trade_name: e.target.value })}
              hint={theirHint("trade_name")}
              error={errorFor("trade_name")}
            />
            <AddressFields
              legend="Principal place of business"
              value={values.address}
              onChange={(address) => edit({ ...values, address })}
              states={stateOptions}
              errorFor={(p) => errorFor(`address.${p}`) ?? (p === "line1" ? errorFor("address") : undefined)}
              hint={theirHint("address")}
            />
            <RadioGroup<Einvoice>
              legend="Has your business's total turnover (all GSTINs on your PAN) been above the e-invoicing limit in any financial year since 2017-18?"
              name="einvoice_history"
              options={EINVOICE}
              value={values.einvoice_history}
              onChange={(v) => edit({ ...values, einvoice_history: v })}
              hint={theirHint("einvoice_history") ?? "If you're not sure, ask your CA."}
              error={errorFor("einvoice_history")}
            />
            <RadioGroup<Band>
              legend={`Turnover this financial year (FY ${thisFy})`}
              name="this_band"
              options={BAND_OPTIONS}
              value={values.this_band}
              onChange={(v) => edit({ ...values, this_band: v })}
              hint={theirHint("this_band") ?? "Ask your CA if you're not sure which applies."}
            />
            <RadioGroup<Band>
              legend={`Turnover last financial year (FY ${lastFy})`}
              name="last_band"
              options={BAND_OPTIONS}
              value={values.last_band}
              onChange={(v) => edit({ ...values, last_band: v })}
              hint={
                theirHint("last_band") ??
                (values.last_band ? "This decides whether 4-digit HSN codes are enough on your invoices." : "Not set yet. This decides whether 4-digit HSN codes are enough on your invoices.")
              }
            />
          </fieldset>
          {canEdit && (
            <div className="actions">
              <Button type="submit" busy={save.isPending} disabled={!dirty}>
                Save changes
              </Button>
            </div>
          )}
        </form>
        <p>
          <Link to={`/b/${businessId}/settings/filing`}>Filing frequency</Link>
        </p>
      </main>
    </>
  );
}
