import type { ReactNode } from "react";

export function Banner({ tone = "info", children }: { tone?: "info" | "error"; children: ReactNode }) {
  return (
    <div className={`banner banner-${tone}`} role={tone === "error" ? "alert" : "status"}>
      {children}
    </div>
  );
}
