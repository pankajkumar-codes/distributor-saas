import type { PasswordPolicy } from "./usePasswordPolicy";

export type PasswordRule = { id: string; label: string; ok: boolean | null };

/**
 * The rules to show, from the server's list (GET /auth/password-policy), ticked as the person types. The list, its
 * wording, the length and the allowed special characters are all the server's; only "does this text meet rule X"
 * lives here. A rule id this screen does not know gets `ok: null`: it is listed, never blocks, and the server
 * decides (it stays the authority for every rule, and also refuses very common passwords).
 */
export function passwordRules(password: string, policy: PasswordPolicy): PasswordRule[] {
  const chars = [...password];
  const test: Record<string, boolean> = {
    length: chars.length >= policy.min_length && chars.length <= policy.max_length,
    upper: /[A-Z]/.test(password),
    lower: /[a-z]/.test(password),
    digit: /[0-9]/.test(password),
    special: chars.some((c) => policy.specials.includes(c)),
  };
  return policy.rules.map((r) => ({ id: r.id, label: r.label, ok: r.id in test ? test[r.id] : null }));
}

/** False only while a rule we can check is not met. With no policy yet (loading, or the call failed) the server decides. */
export function passwordOk(password: string, policy: PasswordPolicy | undefined): boolean {
  return !policy || passwordRules(password, policy).every((r) => r.ok !== false);
}
