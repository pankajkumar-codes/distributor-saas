import { useId } from "react";

export type BusinessType = "retailer" | "wholesaler" | "distributor" | "manufacturer" | "online_seller" | "service_provider" | "other";

export const BUSINESS_TYPES: { value: BusinessType; label: string }[] = [
  { value: "retailer", label: "Retailer" },
  { value: "wholesaler", label: "Wholesaler" },
  { value: "distributor", label: "Distributor" },
  { value: "manufacturer", label: "Manufacturer" },
  { value: "online_seller", label: "Online seller" },
  { value: "service_provider", label: "Service provider" },
  { value: "other", label: "Other" },
];

/** Each type once, in the list's own order, so the same choice always reads (and compares) the same. */
export const orderedTypes = (values: readonly string[]): BusinessType[] => BUSINESS_TYPES.map((o) => o.value).filter((v) => values.includes(v));

/**
 * What best describes the business: choose all that apply (D-095). Optional, and nothing in the app waits on it. The
 * server holds the rule; this only offers the words it accepts.
 */
export function BusinessTypeField({
  value,
  onChange,
  error,
}: {
  value: BusinessType[];
  onChange: (v: BusinessType[]) => void;
  error?: string;
}) {
  const id = useId();
  const toggle = (t: BusinessType, on: boolean) => onChange(orderedTypes(on ? [...value, t] : value.filter((v) => v !== t)));
  return (
    <fieldset className="field">
      <legend>What best describes your business? (optional)</legend>
      {BUSINESS_TYPES.map((o) => (
        <label key={o.value} className="check-line">
          <input type="checkbox" aria-describedby={`${id}-hint`} aria-invalid={error ? true : undefined} checked={value.includes(o.value)} onChange={(e) => toggle(o.value, e.target.checked)} /> {o.label}
        </label>
      ))}
      <p id={`${id}-hint`} className={error ? "error" : "hint"}>
        {error ?? "Choose all that apply. You can change this later in Business setup."}
      </p>
    </fieldset>
  );
}
