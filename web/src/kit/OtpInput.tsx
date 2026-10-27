import { useRef, type ClipboardEvent, type KeyboardEvent } from "react";

type Props = { value: string; onChange: (value: string) => void; length?: number; error?: string; errorId?: string };

/** The 6-box code entry: typing moves on, Backspace moves back, a paste fills every box. */
export function OtpInput({ value, onChange, length = 6, error, errorId }: Props) {
  const boxes = useRef<(HTMLInputElement | null)[]>([]);
  const digits = Array.from({ length }, (_, i) => value[i] ?? "");

  const focus = (i: number) => boxes.current[Math.max(0, Math.min(length - 1, i))]?.focus();

  const put = (i: number, typed: string) => {
    const clean = typed.replace(/\D/g, "");
    if (!clean) return;
    const at = Math.min(i, value.length); // no gaps: a digit typed past the end lands at the end
    onChange((value.slice(0, at) + clean + value.slice(at + clean.length)).slice(0, length));
    focus(at + clean.length);
  };

  const onKeyDown = (i: number, e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key !== "Backspace") return;
    e.preventDefault();
    const at = digits[i] ? i : i - 1;
    if (at < 0) return;
    onChange(value.slice(0, at));
    focus(at);
  };

  const onPaste = (e: ClipboardEvent<HTMLInputElement>) => {
    e.preventDefault();
    const pasted = e.clipboardData.getData("text").replace(/\D/g, "").slice(0, length);
    if (!pasted) return;
    onChange(pasted);
    focus(pasted.length);
  };

  return (
    <fieldset className="otp" aria-describedby={error ? errorId : undefined}>
      <legend>Code</legend>
      {digits.map((digit, i) => (
        <input
          key={i}
          ref={(el) => {
            boxes.current[i] = el;
          }}
          value={digit}
          inputMode="numeric"
          autoComplete={i === 0 ? "one-time-code" : "off"}
          maxLength={i === 0 ? length : 1}
          aria-label={`Digit ${i + 1} of ${length}`}
          aria-invalid={error ? true : undefined}
          onChange={(e) => {
            const typed = e.target.value;
            // A box that already held a digit gets the new one typed after it.
            put(i, digit && typed.length > 1 && typed.startsWith(digit) ? typed.slice(1) : typed);
          }}
          onKeyDown={(e) => onKeyDown(i, e)}
          onPaste={onPaste}
          onFocus={(e) => e.target.select()}
        />
      ))}
    </fieldset>
  );
}
