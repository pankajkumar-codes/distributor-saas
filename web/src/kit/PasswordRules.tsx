import { usePasswordPolicy } from "../auth/usePasswordPolicy";

/** The password rules from the server, with the ones the last attempt missed marked. */
export function PasswordRules({ unmet = [] }: { unmet?: string[] }) {
  const { data } = usePasswordPolicy();
  if (!data) return null;
  return (
    <ul className="note" style={{ listStyle: "none", paddingLeft: 0 }}>
      {data.rules.map((r) => (
        <li key={r.id} data-unmet={unmet.includes(r.id) || undefined}>
          <span aria-hidden="true">{unmet.includes(r.id) ? "✗ " : "• "}</span>
          {r.label}
        </li>
      ))}
    </ul>
  );
}
