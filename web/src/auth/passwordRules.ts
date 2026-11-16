/** The characters that count as the special one. Shown on screen next to the rule. */
export const SPECIAL_CHARACTERS = "!@#$%^&*()-_=+[]{}.,?";

export type PasswordRule = { id: string; label: string; ok: boolean };

/**
 * The sign-up password rules, checked as the person types. The server stays the authority
 * (it also refuses very common passwords); this only keeps "Email me a code" off until the
 * visible rules pass. Pankaj's rule, 2026-11-16.
 */
export function passwordRules(password: string): PasswordRule[] {
  return [
    { id: "length", label: "At least 10 characters", ok: [...password].length >= 10 },
    { id: "upper", label: "One uppercase letter", ok: /[A-Z]/.test(password) },
    { id: "lower", label: "One lowercase letter", ok: /[a-z]/.test(password) },
    { id: "digit", label: "One digit", ok: /[0-9]/.test(password) },
    {
      id: "special",
      label: `One special character: ${SPECIAL_CHARACTERS}`,
      ok: [...password].some((c) => SPECIAL_CHARACTERS.includes(c)),
    },
  ];
}

export const passwordOk = (password: string) => passwordRules(password).every((r) => r.ok);
