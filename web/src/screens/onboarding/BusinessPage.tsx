import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api, call } from "../../api/client";
import { useStateCodes } from "../../api/useStateCodes";
import { errorText, type ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { fyIst, previousFy, quarterStartIst } from "../../format/dates";
import { checkGstin, gstinMessage } from "../../format/gstin";
import { BusinessTypeUpcoming } from "../../kit/BusinessTypeUpcoming";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { CheckboxGroup } from "../../kit/CheckboxGroup";
import { Field } from "../../kit/Field";
import { RadioGroup } from "../../kit/RadioGroup";
import { SelectField } from "../../kit/SelectField";
import { TopBar } from "../../kit/TopBar";
import { warningText } from "./warnings";

type NewBusiness = components["schemas"]["NewBusinessProfile"];
type Created = components["schemas"]["NewBusinessOut"];
type Band = NewBusiness["turnover_band"];
type Einvoice = NewBusiness["einvoice_history"];
type Frequency = components["schemas"]["FrequencyIn"]["frequency"];
type Errors = Record<string, string | undefined>;
export type Channels = components["schemas"]["ChannelsIn"];

export const PLATFORM_OPTIONS: { value: keyof Channels; label: string; sub?: string }[] = [
  { value: "amazon", label: "Amazon" },
  { value: "flipkart", label: "Flipkart" },
  { value: "meesho", label: "Meesho" },
  { value: "own_invoices", label: "Own sales invoices", sub: "Invoices you make yourself, as PDF and/or Excel" },
];
export const NO_PLATFORMS: Channels = { amazon: false, flipkart: false, meesho: false, own_invoices: false };
/** The fields that belong to step 3; a refusal naming one sends the user back there. */
const STEP3_FIELDS = /^(registration|legal_name|trade_name|turnover_band|einvoice_history|address)(\.|$)/;

export const BAND_OPTIONS: { value: Band; label: string }[] = [
  { value: "up_to_threshold", label: "Up to the limit for quarterly filing (QRMP)" },
  { value: "above_threshold", label: "Above that limit" },
];

// The server's words are terse ("enter the enrolment number"); these are the screen's.
const BY_CODE: Record<string, string> = {
  state_code_unknown: "Choose a state from the list.",
  state_code_mismatch: "The state comes from the first two digits of your GSTIN.",
  registration_mixed: "Enter either a GSTIN or an enrolment number, not both.",
  enrolment_number_required: "Enter the enrolment number.",
  state_code_required: "Choose the state you're enrolled in.",
};
const INVALID: Record<string, string> = { "address.pin": "Enter a 6-digit PIN code." };

/**
 * Where a POST /b refusal shows: under the field the server names, in the screen's words.
 * `registration` alone (no GSTIN or enrolment sent) belongs to the GSTIN field.
 */
export function fieldError(error: ApiError, gstin: string): { field: string; text: string } | null {
  if (!error.field) return null;
  const field = error.field === "registration" ? "registration.gstin" : error.field;
  const text = error.code.startsWith("gstin_")
    ? gstinMessage(error.code, gstin)
    : (BY_CODE[error.code] ?? (error.code === "invalid" ? (INVALID[field] ?? "Check this entry.") : errorText(error)));
  return { field, text };
}

/**
 * /onboarding/business (M2 step 3). The GSTIN check here is a hint only, from the same
 * cases the server tests; POST /b decides. One Idempotency-Key per form for the business
 * and one for the frequency, so a retry or a double tap creates one of each (LLD-0 §3.8).
 */
export function BusinessPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const states = useStateCodes();
  const keys = useRef({ business: crypto.randomUUID(), frequency: crypto.randomUUID() });

  const [kind, setKind] = useState<"gstin" | "enrolment">("gstin");
  const [gstin, setGstin] = useState("");
  const [gstinBlurred, setGstinBlurred] = useState(false);
  const [enrolment, setEnrolment] = useState("");
  const [enrolState, setEnrolState] = useState("");
  const [legalName, setLegalName] = useState("");
  const [tradeName, setTradeName] = useState("");
  const [band, setBand] = useState<Band | "">("");
  const [lastBand, setLastBand] = useState<Band | "not_sure" | "">("");
  const [einvoice, setEinvoice] = useState<Einvoice | "">("");
  const [frequency, setFrequency] = useState<Frequency | "">("");
  const [line1, setLine1] = useState("");
  const [line2, setLine2] = useState("");
  const [city, setCity] = useState("");
  const [pin, setPin] = useState("");
  const [addressState, setAddressState] = useState("");
  const [missing, setMissing] = useState<Errors>({});
  const [tries, setTries] = useState(0);
  const [step, setStep] = useState<3 | 4>(3);
  const [platforms, setPlatforms] = useState<Channels>(NO_PLATFORMS);

  const check = checkGstin(gstin);
  const stateName = (code: string | null) => states.data?.find((s) => s.code === code)?.name;
  const gstinStateUnknown = check.ok && states.isSuccess && !stateName(check.stateCode);
  const regState = kind === "gstin" ? (check.ok && !gstinStateUnknown ? check.stateCode : null) : enrolState || null;
  const addressStateShown = addressState || regState || "";
  const startsOn = quarterStartIst();
  const lastFy = previousFy(fyIst());

  const finish = (id: string, warnings: string[]) => navigate(`/b/${id}/home`, { replace: true, state: { warnings } });

  const choose = useMutation<components["schemas"]["FrequencyOut"], ApiError, { id: string; frequency: Frequency; warnings: string[] }>({
    mutationFn: ({ id, frequency }) =>
      call(() =>
        api.POST("/api/v1/b/{business_id}/filing-profile/frequency", {
          params: { path: { business_id: id }, header: { "Idempotency-Key": keys.current.frequency } },
          body: { frequency, effective_from: startsOn },
        }),
      ),
    onSuccess: (out, { id, warnings }) => finish(id, [...warnings, ...out.warnings]),
  });

  const create = useMutation<Created, ApiError, { body: NewBusiness; frequency: Frequency | null }>({
    mutationFn: ({ body }) =>
      call(() => api.POST("/api/v1/b", { body, params: { header: { "Idempotency-Key": keys.current.business } } })),
    onSuccess: async (out, { frequency }) => {
      await queryClient.invalidateQueries({ queryKey: ["me", "businesses"] });
      let warnings = out.warnings;
      // Last year's band is optional and has its own route; the business exists already, so a
      // failure here only asks the user to add it in Settings rather than stopping sign-up.
      if (lastBand && lastBand !== "not_sure") {
        try {
          await call(() =>
            api.PUT("/api/v1/b/{business_id}/turnover-bands/{fy}", {
              params: { path: { business_id: out.business_id, fy: lastFy } },
              body: { band: lastBand, declared_turnover: null },
            }),
          );
        } catch (e) {
          // A replayed create (same Idempotency-Key, after the frequency step failed) finds the
          // band already there. The server answers a PUT with no If-Match on an existing band
          // with 422 if_match_required (409 stale_record if it was set meanwhile): either way
          // it was saved, not lost.
          const code = (e as ApiError).code;
          if (code !== "if_match_required" && code !== "stale_record") warnings = [...warnings, "previous_band_not_saved"];
        }
      }
      // Platforms are saved after the create, like last year's band: a failure only asks the user to
      // set them in Settings. The same answer twice is harmless, so a replay needs no special case.
      try {
        await call(() => api.PUT("/api/v1/b/{business_id}/channels", { params: { path: { business_id: out.business_id } }, body: platforms }));
      } catch {
        warnings = [...warnings, "platforms_not_saved"];
      }
      if (frequency) choose.mutate({ id: out.business_id, frequency, warnings });
      else finish(out.business_id, warnings);
    },
  });

  // After a refused submit, take the keyboard and screen reader to the first problem.
  useEffect(() => {
    if (tries) document.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
  }, [tries, create.error, step]);

  const blank = (v: string) => v.trim() || null;
  const step3Errors = (): Errors => {
    const found: Errors =
      kind === "gstin"
        ? {
            "registration.gstin": !gstin.trim()
              ? "Enter your GSTIN."
              : !check.ok
                ? gstinMessage(check.errors[0], gstin)
                : gstinStateUnknown
                  ? gstinMessage("gstin_state")
                  : undefined,
          }
        : {
            "registration.enrolment_number": enrolment.trim() ? undefined : "Enter the enrolment number.",
            "registration.state_code": enrolState ? undefined : "Choose the state you're enrolled in.",
          };
    found.turnover_band = band ? undefined : "Choose one.";
    found.einvoice_history = einvoice ? undefined : "Choose one.";
    found["address.pin"] = !pin.trim() || /^[0-9]{6}$/.test(pin.trim()) ? undefined : INVALID["address.pin"];
    return found;
  };
  const step4Errors = (): Errors => ({
    platforms: Object.values(platforms).some(Boolean) ? undefined : "Pick at least one to continue.",
    frequency: kind === "gstin" && !frequency ? "Choose how often you file GST." : undefined,
  });

  // Step 3 only checks what step 3 asks; nothing is sent until the last step.
  const next = (e: FormEvent) => {
    e.preventDefault();
    const found = step3Errors();
    setMissing(found);
    setTries((n) => n + 1);
    if (!Object.values(found).some(Boolean)) setStep(4);
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (create.isPending || create.isSuccess) return;
    const found = step4Errors();
    setMissing(found);
    setTries((n) => n + 1);
    if (Object.values(found).some(Boolean) || !band || !einvoice) return;
    create.mutate({
      body: {
        registration:
          kind === "gstin"
            ? { kind, gstin: check.normalised }
            : { kind, enrolment_number: enrolment.trim(), state_code: enrolState },
        legal_name: blank(legalName),
        trade_name: blank(tradeName),
        turnover_band: band,
        einvoice_history: einvoice,
        address: {
          line1: blank(line1),
          line2: blank(line2),
          city: blank(city),
          pin: blank(pin),
          state_code: addressStateShown || null,
        },
      },
      frequency: kind === "gstin" && frequency ? frequency : null,
    });
  };

  const server = create.error ? fieldError(create.error, gstin) : null;
  useEffect(() => {
    if (create.error && STEP3_FIELDS.test(fieldError(create.error, gstin)?.field ?? "")) setStep(3);
  }, [create.error]);
  const err = (field: string) => missing[field] ?? (server?.field === field ? server.text : undefined);
  const shown = new Set([
    ...(kind === "gstin" ? ["registration.gstin", "frequency"] : ["registration.enrolment_number", "registration.state_code"]),
    "platforms",
    ...["legal_name", "trade_name", "turnover_band", "einvoice_history"],
    ...["address.line1", "address.line2", "address.city", "address.pin", "address.state_code"],
  ]);
  const bannerError = create.error && !(server && shown.has(server.field)) ? create.error : null;

  const stateOptions = (states.data ?? []).map((s) => ({ value: s.code, label: `${s.name} (${s.code})` }));
  const gstinLive = gstinBlurred || check.normalised.length >= 15 ? check : null;
  const gstinHint = [
    check.ok && !gstinStateUnknown
      ? `Format and check digit look right. State code ${check.stateCode}${stateName(check.stateCode) ? ` (${stateName(check.stateCode)})` : ""}.`
      : null,
    "We check the format and check digit only, not with the GST portal.",
    ...(check.ok ? check.warnings.map(warningText) : []),
  ]
    .filter(Boolean)
    .join(" ");
  const gstinError =
    err("registration.gstin") ??
    (gstinLive && !gstinLive.ok ? gstinMessage(gstinLive.errors[0], gstin) : gstinStateUnknown ? gstinMessage("gstin_state") : undefined);

  if (create.isSuccess) {
    // The business exists; only the frequency is left. Retrying reuses its key.
    const id = create.data.business_id;
    return (
      <>
        <TopBar />
        <main className="page">
          <p className="step">Step 3 of 4</p>
          <h1>Your business and GST</h1>
          {choose.isError ? (
            <>
              <Banner tone="error">
                Your business is saved, but we couldn't save how often you file. {errorText(choose.error)}
              </Banner>
              <div className="actions">
                <Button type="button" onClick={() => choose.variables && choose.mutate(choose.variables)}>
                  Try again
                </Button>
                <Button type="button" variant="link" onClick={() => finish(id, create.data.warnings)}>
                  Skip for now
                </Button>
              </div>
            </>
          ) : (
            <p aria-busy="true">Saving how often you file…</p>
          )}
        </main>
      </>
    );
  }

  return (
    <>
      <TopBar />
      <main className="page">
        <p className="step">Step {step} of 4</p>
        <h1>{step === 3 ? "Your business and GST" : "Where you sell and how you file"}</h1>
        <form onSubmit={step === 3 ? next : submit} noValidate>
          {bannerError &&
            (bannerError.code === "idempotency_mismatch" ? (
              <Banner tone="error">
                This business may already have been saved. <Link to="/businesses">Check your businesses</Link> before
                you try again.
              </Banner>
            ) : (
              <Banner tone="error">{errorText(bannerError)}</Banner>
            ))}
          {states.isError && <Banner tone="error">We couldn't load the list of states. {errorText(states.error)}</Banner>}

          {step === 3 && (
            <>
          {kind === "gstin" ? (
            <>
              <Field
                label="GSTIN"
                autoComplete="off"
                autoCapitalize="characters"
                spellCheck={false}
                maxLength={20}
                value={gstin}
                onChange={(e) => setGstin(e.target.value)}
                onBlur={() => setGstinBlurred(true)}
                hint={gstinHint}
                error={gstinError}
              />
              <Button type="button" variant="link" onClick={() => setKind("enrolment")}>
                Use enrolment number
              </Button>
            </>
          ) : (
            <>
              <Field
                label="Enrolment number"
                autoComplete="off"
                spellCheck={false}
                value={enrolment}
                onChange={(e) => setEnrolment(e.target.value)}
                hint="If you don't have a GSTIN yet. You add the GSTIN later, before filing."
                error={err("registration.enrolment_number")}
              />
              <SelectField
                label="State you're enrolled in"
                options={stateOptions}
                value={enrolState}
                onChange={(e) => setEnrolState(e.target.value)}
                error={err("registration.state_code")}
              />
              <Button type="button" variant="link" onClick={() => setKind("gstin")}>
                Use GSTIN
              </Button>
            </>
          )}

          <BusinessTypeUpcoming />
          <Field
            label="Legal name (as on GST certificate)"
            autoComplete="organization"
            value={legalName}
            onChange={(e) => setLegalName(e.target.value)}
            error={err("legal_name")}
          />
          <Field
            label="Trade name (optional)"
            value={tradeName}
            onChange={(e) => setTradeName(e.target.value)}
            error={err("trade_name")}
          />

          <RadioGroup<Band>
            legend="Turnover this financial year (declared)"
            name="turnover_band"
            options={BAND_OPTIONS}
            value={band}
            onChange={setBand}
            hint="Ask your CA if you're not sure which applies."
            error={err("turnover_band")}
          />
          <RadioGroup<Band | "not_sure">
            legend={`What was your turnover last financial year (FY ${lastFy})? (optional)`}
            name="previous_turnover_band"
            options={[...BAND_OPTIONS, { value: "not_sure", label: "Not sure" }]}
            value={lastBand}
            onChange={setLastBand}
            hint="This decides whether 4-digit HSN codes are enough on your invoices. You can change it later in Settings → Business details."
          />
          <RadioGroup<Einvoice>
            legend="Has your business's total turnover (all GSTINs on your PAN) been above the e-invoicing limit in any financial year since 2017-18?"
            name="einvoice_history"
            options={[
              { value: "yes", label: "Yes" },
              { value: "no", label: "No" },
              { value: "not_sure", label: "Not sure" },
            ]}
            value={einvoice}
            onChange={setEinvoice}
            error={err("einvoice_history")}
          />

          <h2>Principal place of business</h2>
          <Field
            label="Address line 1"
            autoComplete="address-line1"
            value={line1}
            onChange={(e) => setLine1(e.target.value)}
            error={err("address.line1")}
          />
          <Field
            label="Address line 2 (optional)"
            autoComplete="address-line2"
            value={line2}
            onChange={(e) => setLine2(e.target.value)}
            error={err("address.line2")}
          />
          <Field
            label="City or town"
            autoComplete="address-level2"
            value={city}
            onChange={(e) => setCity(e.target.value)}
            error={err("address.city")}
          />
          <Field
            label="PIN code"
            autoComplete="postal-code"
            inputMode="numeric"
            maxLength={6}
            value={pin}
            onChange={(e) => setPin(e.target.value)}
            error={err("address.pin")}
          />
          <SelectField
            label="State"
            options={stateOptions}
            value={addressStateShown}
            onChange={(e) => setAddressState(e.target.value)}
            hint={
              regState && addressStateShown && addressStateShown !== regState
                ? warningText("address_state_mismatch")
                : "If the address is in another state, we warn you: a GSTIN belongs to one state."
            }
            error={err("address.state_code")}
          />
              <Button type="submit">Continue</Button>
            </>
          )}
          {step === 4 && (
            <>
          <CheckboxGroup<keyof Channels>
            legend="Which platforms do you sell on?"
            options={PLATFORM_OPTIONS}
            value={platforms}
            onChange={setPlatforms}
            hint="Tick every one that applies. At least one is needed. You can change this later."
            error={err("platforms")}
          />
          {kind === "gstin" && (
            <RadioGroup<Frequency>
              legend="How often do you file GST?"
              name="frequency"
              options={[
                { value: "monthly", label: "Monthly", sub: "GSTR-1 and GSTR-3B every month" },
                { value: "quarterly", label: "Quarterly (QRMP)", sub: "GSTR-1 and GSTR-3B every quarter" },
              ]}
              value={frequency}
              onChange={setFrequency}
              hint="This sets the deadlines we show. It doesn't change anything on the GST portal."
              error={err("frequency")}
            />
          )}

          <div className="actions">
            <Button type="button" variant="link" onClick={() => setStep(3)}>
              Back
            </Button>
            <Button type="submit" busy={create.isPending || choose.isPending}>
              Finish and see my filing home
            </Button>
          </div>
            </>
          )}
        </form>
      </main>
    </>
  );
}
