import { useEffect } from "react";

import { APP_NAME } from "../brand";

/** Sets the browser tab's title for the screen it wraps ("Upload your reports · Kartaa"). */
export function PageTitle({ title, children }: { title: string; children: React.ReactNode }) {
  useEffect(() => {
    document.title = `${title} · ${APP_NAME}`;
  }, [title]);
  return <>{children}</>;
}
