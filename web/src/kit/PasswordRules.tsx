import { passwordRules } from "../auth/passwordRules";
import { usePasswordPolicy } from "../auth/usePasswordPolicy";

/**
 * The server's password rules as a checklist that updates while typing. Each line says met or not met in words,
 * not by colour alone. Nothing shows until the list has loaded.
 */
export function PasswordRules({ password, id }: { password: string; id: string }) {
  const { data } = usePasswordPolicy();
  if (!data) return null;
  return (
    <ul className="rules" id={id}>
      {passwordRules(password, data).map((r) => (
        <li key={r.id} className={r.ok ? "rule-ok" : undefined}>
          <span aria-hidden="true">{r.ok ? "✓" : "○"}</span> {r.label}
          {r.ok !== null && <span className="visually-hidden">{r.ok ? " (done)" : " (not yet)"}</span>}
        </li>
      ))}
    </ul>
  );
}
