import type { ButtonHTMLAttributes } from "react";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" | "link"; busy?: boolean };

export function Button({ variant = "primary", busy = false, disabled, children, className, ...rest }: Props) {
  return (
    <button {...rest} className={`btn btn-${variant}${className ? ` ${className}` : ""}`} disabled={disabled || busy} aria-busy={busy || undefined}>
      {children}
    </button>
  );
}
