import { useId } from "react";

type Option<T extends string> = { value: T; label: string };
type Props<T extends string> = {
  legend: string;
  options: Option<T>[];
  value: Record<T, boolean>;
  onChange: (value: Record<T, boolean>) => void;
  hint?: string;
  error?: string;
  disabled?: boolean;
};

/** Checkboxes in a fieldset (any number can be ticked): the legend is the question, hint and error are read with it. */
export function CheckboxGroup<T extends string>({ legend, options, value, onChange, hint, error, disabled }: Props<T>) {
  const id = useId();
  const described = [hint && `${id}-hint`, error && `${id}-error`].filter(Boolean).join(" ");
  return (
    <fieldset className="field radios" aria-describedby={described || undefined} disabled={disabled}>
      <legend>{legend}</legend>
      {options.map((o) => (
        <label key={o.value} className="radio">
          <input
            type="checkbox"
            checked={value[o.value]}
            aria-invalid={error ? true : undefined}
            onChange={(e) => onChange({ ...value, [o.value]: e.target.checked })}
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
