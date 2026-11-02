import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { quarterStartIst } from "../../format/dates";
import { checkGstin, gstinMessage } from "../../format/gstin";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
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

function useStateCodes() {
  return useQuery<components["schemas"]["StateCode"][], ApiError>({
    queryKey: ["refdata", "state-codes"],
    // 96 (other country) is a place of supply only, never a registration or address state.
    queryFn: async () =>
      (await call(() => api.GET("/api/v1/refdata/state-codes"))).states.filter((s) => s.code !== "96"),
    staleTime: Infinity,
  });
}

const display = (day: string) =>
  new Date(`${day}T00:00:00Z`).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });

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
  const [einvoice, setEinvoice] = useState<Einvoice | "">("");
  const [frequency, setFrequency] = useState<Frequency | "">("");
  const [line1, setLine1] = useState("");
  const [line2, setLine2] = useState("");
  const [city, setCity] = useState("");
  const [pin, setPin] = useState("");
  const [addressState, setAddressState] = useState("");
  const [missing, setMissing] = useState<Errors>({});
  const [tries, setTries] = useState(0);

  const check = checkGstin(gstin);
  const stateName = (code: string | null) => states.data?.find((s) => s.code === code)?.name;
  const gstinStateUnknown = check.ok && states.isSuccess && !stateName(check.stateCode);
  const regState = kind === "gstin" ? (check.ok && !gstinStateUnknown ? check.stateCode : null) : enrolState || null;
  const addressStateShown = addressState || regState || "";
  const startsOn = quarterStartIst();

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
      if (frequency) choose.mutate({ id: out.business_id, frequency, warnings: out.warnings });
      else finish(out.business_id, out.warnings);
    },
  });

  // After a refused submit, take the keyboard and screen reader to the first problem.
  useEffect(() => {
    if (tries) document.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
  }, [tries, create.error]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (create.isPending || create.isSuccess) return;
    const blank = (v: string) => v.trim() || null;
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
            frequency: frequency ? undefined : "Choose how often you file GSTR-1.",
          }
        : {
            "registration.enrolment_number": enrolment.trim() ? undefined : "Enter the enrolment number.",
            "registration.state_code": enrolState ? undefined : "Choose the state you're enrolled in.",
          };
    found.turnover_band = band ? undefined : "Choose one.";
    found.einvoice_history = einvoice ? undefined : "Choose one.";
    found["address.pin"] = !pin.trim() || /^[0-9]{6}$/.test(pin.trim()) ? undefined : INVALID["address.pin"];
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
  const err = (field: string) => missing[field] ?? (server?.field === field ? server.text : undefined);
  const shown = new Set([
    ...(kind === "gstin" ? ["registration.gstin", "frequency"] : ["registration.enrolment_number", "registration.state_code"]),
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
        <p className="step">Step 3 of 4</p>
        <h1>Your business and GST</h1>
        <form onSubmit={submit} noValidate>
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
            options={[
              { value: "up_to_threshold", label: "Up to the limit for quarterly filing (QRMP)" },
              { value: "above_threshold", label: "Above that limit" },
            ]}
            value={band}
            onChange={setBand}
            hint="Ask your CA if you're not sure which applies."
            error={err("turnover_band")}
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

          {kind === "gstin" && (
            <RadioGroup<Frequency>
              legend="How often do you file GSTR-1?"
              name="frequency"
              options={[
                { value: "quarterly", label: "Every quarter (QRMP)" },
                { value: "monthly", label: "Every month" },
              ]}
              value={frequency}
              onChange={setFrequency}
              hint={`This applies from the quarter starting ${display(startsOn)}. If you're not sure, ask your CA.`}
              error={err("frequency")}
            />
          )}

          <Button type="submit" busy={create.isPending || choose.isPending}>
            Continue
          </Button>
        </form>
      </main>
    </>
  );
}
