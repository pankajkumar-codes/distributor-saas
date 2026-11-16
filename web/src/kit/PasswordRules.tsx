import { passwordRules } from "../auth/passwordRules";

/** The rules as a checklist that updates while typing. Each line says met or not met in words, not by colour alone. */
export function PasswordRules({ password, id }: { password: string; id: string }) {
  return (
    <ul className="rules" id={id}>
      {passwordRules(password).map((r) => (
        <li key={r.id} className={r.ok ? "rule-ok" : undefined}>
          <span aria-hidden="true">{r.ok ? "✓" : "○"}</span> {r.label}
          <span className="visually-hidden">{r.ok ? " (done)" : " (not yet)"}</span>
        </li>
      ))}
    </ul>
  );
}
