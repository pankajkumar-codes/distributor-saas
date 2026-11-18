import { useId } from "react";

export type BusinessType = "distributor" | "retail";

export const BUSINESS_TYPES: { value: BusinessType; label: string }[] = [
  { value: "distributor", label: "Distributor" },
  { value: "retail", label: "Retail" },
];

/**
 * ON-7, switched on in R2-M1: is this a distributor or a retail business. Optional: the empty
 * choice means "not chosen", which is what every R1 business has. The server holds the rule;
 * this only offers the two words it accepts.
 */
export function BusinessTypeField({
  value,
  onChange,
  error,
}: {
  value: BusinessType | "";
  onChange: (v: BusinessType | "") => void;
  error?: string;
}) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>Business type (optional)</label>
      <select
        id={id}
        value={value}
        aria-describedby={`${id}-hint`}
        aria-invalid={error ? true : undefined}
        onChange={(e) => onChange(e.target.value as BusinessType | "")}
      >
        <option value="">Not chosen</option>
        {BUSINESS_TYPES.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <p id={`${id}-hint`} className={error ? "error" : "hint"}>
        {error ?? "Distributor or retail. You can change it later in Business setup."}
      </p>
    </div>
  );
}
