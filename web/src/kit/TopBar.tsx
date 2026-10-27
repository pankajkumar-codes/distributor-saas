import { useNavigate } from "react-router-dom";

import { signOut } from "../auth/session";
import { Button } from "./Button";

export function TopBar({ title, gstin }: { title?: string; gstin?: string | null }) {
  const navigate = useNavigate();
  return (
    <header className="topbar">
      <div>
        {title && <strong>{title}</strong>}
        {gstin && <span className="hint"> · GSTIN {gstin}</span>}
      </div>
      <Button
        type="button"
        variant="link"
        onClick={async () => {
          await signOut();
          navigate("/signin", { replace: true });
        }}
      >
        Sign out
      </Button>
    </header>
  );
}
