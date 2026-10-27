import type { ButtonHTMLAttributes } from "react";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "link"; busy?: boolean };

export function Button({ variant = "primary", busy = false, disabled, children, ...rest }: Props) {
  return (
    <button className={`btn btn-${variant}`} disabled={disabled || busy} aria-busy={busy || undefined} {...rest}>
      {children}
    </button>
  );
}
