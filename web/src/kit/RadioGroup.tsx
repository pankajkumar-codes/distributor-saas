import { useId } from "react";

type Option<T extends string> = { value: T; label: string };
type Props<T extends string> = {
  legend: string;
  name: string;
  options: Option<T>[];
  value: T | "";
  onChange: (value: T) => void;
  hint?: string;
  error?: string;
};

/** Radios in a fieldset: the legend is the question, and the hint and error are read with it. */
export function RadioGroup<T extends string>({ legend, name, options, value, onChange, hint, error }: Props<T>) {
  const id = useId();
  const described = [hint && `${id}-hint`, error && `${id}-error`].filter(Boolean).join(" ");
  return (
    <fieldset className="field radios" aria-describedby={described || undefined}>
      <legend>{legend}</legend>
      {options.map((o) => (
        <label key={o.value} className="radio">
          <input
            type="radio"
            name={name}
            value={o.value}
            checked={value === o.value}
            aria-invalid={error ? true : undefined}
            onChange={() => onChange(o.value)}
          />
          {o.label}
        </label>
      ))}
      {hint && (
        <p id={`${id}-hint`} className="hint">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="error">
          {error}
        </p>
      )}
    </fieldset>
  );
}
