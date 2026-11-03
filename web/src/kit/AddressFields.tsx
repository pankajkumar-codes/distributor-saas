import type { components } from "../api/schema";
import { Field } from "./Field";
import { SelectField } from "./SelectField";

export const ADDRESS_PARTS = ["line1", "line2", "city", "pin", "state_code"] as const;
export type Address = Record<(typeof ADDRESS_PARTS)[number], string>;
export const NO_ADDRESS: Address = { line1: "", line2: "", city: "", pin: "", state_code: "" };

export const addressOf = (a: components["schemas"]["AddressOut"] | null): Address =>
  a ? { line1: a.line1 ?? "", line2: a.line2 ?? "", city: a.city ?? "", pin: a.pin ?? "", state_code: a.state_code ?? "" } : NO_ADDRESS;
export const sameAddress = (a: Address, b: Address) => ADDRESS_PARTS.every((k) => a[k].trim() === b[k].trim());
/** An address as one line, for "Now saved as: …". */
export const addressLine = (a: Address) => ADDRESS_PARTS.map((p) => a[p].trim()).filter(Boolean).join(", ") || "(blank)";
/** The address as the API takes it: a blank part is null. */
export const addressIn = (a: Address): components["schemas"]["AddressIn"] =>
  Object.fromEntries(ADDRESS_PARTS.map((k) => [k, a[k].trim() || null]));

/** The five address fields in a fieldset, each with the server's error for its part. */
export function AddressFields(props: {
  legend: string;
  value: Address;
  onChange: (a: Address) => void;
  states: { value: string; label: string }[];
  errorFor: (part: string) => string | undefined;
  hint?: string;
  stateHint?: string;
}) {
  const { value, onChange, errorFor } = props;
  const set = (k: keyof Address) => (e: { target: { value: string } }) => onChange({ ...value, [k]: e.target.value });
  return (
    <fieldset className="field radios">
      <legend>{props.legend}</legend>
      {props.hint && <p className="hint">{props.hint}</p>}
      <Field label="Address line 1" value={value.line1} onChange={set("line1")} error={errorFor("line1")} />
      <Field label="Address line 2" value={value.line2} onChange={set("line2")} error={errorFor("line2")} />
      <Field label="City or town" value={value.city} onChange={set("city")} error={errorFor("city")} />
      <Field label="PIN code" inputMode="numeric" value={value.pin} onChange={set("pin")} error={errorFor("pin")} />
      <SelectField label="State" options={props.states} value={value.state_code} onChange={set("state_code")} hint={props.stateHint} error={errorFor("state_code")} />
    </fieldset>
  );
}
