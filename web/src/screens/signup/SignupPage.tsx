import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { CodeStep } from "./CodeStep";
import { EmailStep } from "./EmailStep";

// Step 2 is the same /signup URL with the email in history.state, never in a query string,
// so it stays out of browser history and access logs (RM-4.1 row 13). history.state
// survives a reload; the password does not, because it lives only in this component.
type CodeState = { email: string; sentAt: number };

function codeState(state: unknown): CodeState | null {
  const s = state as Partial<CodeState> | null;
  return s && typeof s.email === "string" && typeof s.sentAt === "number" ? { email: s.email, sentAt: s.sentAt } : null;
}

export function SignupPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const step2 = codeState(location.state);

  if (!step2) {
    return (
      <EmailStep
        initialEmail={email}
        initialPassword={password}
        onSent={(sentTo, chosen) => {
          setEmail(sentTo);
          setPassword(chosen);
          navigate("/signup", { state: { email: sentTo, sentAt: Date.now() } satisfies CodeState });
        }}
      />
    );
  }
  return (
    <CodeStep
      email={step2.email}
      sentAt={step2.sentAt}
      password={password}
      onResent={(sentAt) => navigate("/signup", { replace: true, state: { email: step2.email, sentAt } })}
      onBack={() => {
        setEmail(step2.email);
        navigate("/signup", { replace: true, state: null });
      }}
      onPasswordChange={setPassword}
    />
  );
}
